// FILE: workers/face_worker.ts
// Face presence, head pose, gaze, blink rate, multi-face, identity verification
// Uses MediaPipe Face Landmarker WASM

// ── Message Types ────────────────────────────────

// INBOUND (main thread → worker)
type FaceWorkerInbound =
  | { type: 'INIT'; modelPath: string }
  | { type: 'ANALYZE_FRAME'; imageData: ImageData; frameId: number }
  | { type: 'SET_ENROLLMENT'; descriptor: Float32Array }
  | { type: 'SHUTDOWN' };

// OUTBOUND (worker → main thread)
type FaceWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'FRAME_RESULT'; frameId: number; result: FaceAnalysisResult };

interface FaceAnalysisResult {
  faceCount: number;           // 0 = no face, 1 = ok, 2+ = multiple
  headPose: {
    yaw: number;               // degrees: neg=left, pos=right (threshold: ±25°)
    pitch: number;             // degrees: neg=down, pos=up  (threshold: ±20°)
    roll: number;              // degrees (threshold: ±15°)
  } | null;
  gazeOffset: {
    x: number;                 // normalised -1..+1 (threshold: ±0.35)
    y: number;
  } | null;
  blinkRate: number;           // blinks per minute (normal: 12-20)
  earScore: number;            // Eye Aspect Ratio (threshold: < 0.18 = blink)
  identityScore: number | null;// cosine sim vs enrollment (threshold: < 0.6 = mismatch)
  landmarkCount: number;
}

// ── Worker State ─────────────────────────────────
let faceLandmarker: any = null;
let enrollmentDescriptor: Float32Array | null = null;
let blinkTimestamps: number[] = [];
let lastEarBelow: boolean = false;

// ── Helper: Eye Aspect Ratio ─────────────────────
function computeEAR(landmarks: any[], eyeIndices: number[]): number {
  // Simplified EAR computation using MediaPipe landmark indices
  // EAR = (|p2-p6| + |p3-p5|) / (2 * |p1-p4|)
  try {
    const p1 = landmarks[eyeIndices[0]];
    const p2 = landmarks[eyeIndices[1]];
    const p3 = landmarks[eyeIndices[2]];
    const p4 = landmarks[eyeIndices[3]];
    const p5 = landmarks[eyeIndices[4]];
    const p6 = landmarks[eyeIndices[5]];

    const dist = (a: any, b: any) =>
      Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);

    const vertical1 = dist(p2, p6);
    const vertical2 = dist(p3, p5);
    const horizontal = dist(p1, p4);

    if (horizontal === 0) return 0;
    return (vertical1 + vertical2) / (2 * horizontal);
  } catch {
    return 0.25; // default open eye value
  }
}

// MediaPipe eye landmark indices
const LEFT_EYE = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE = [362, 385, 387, 263, 373, 380];

// ── Helper: Head Pose from landmarks ─────────────
function computeHeadPose(landmarks: any[]): { yaw: number; pitch: number; roll: number } | null {
  try {
    // Use nose tip, chin, left/right eye corners, left/right mouth corners
    const noseTip = landmarks[1];
    const chin = landmarks[152];
    const leftEye = landmarks[33];
    const rightEye = landmarks[263];
    const leftMouth = landmarks[61];
    const rightMouth = landmarks[291];

    // Simplified yaw: horizontal displacement of nose relative to eye midpoint
    const eyeMidX = (leftEye.x + rightEye.x) / 2;
    const yaw = (noseTip.x - eyeMidX) * 180; // rough degrees

    // Simplified pitch: vertical displacement of nose relative to eye-chin midpoint
    const eyeMidY = (leftEye.y + rightEye.y) / 2;
    const faceHeight = chin.y - eyeMidY;
    const noseRelative = (noseTip.y - eyeMidY) / (faceHeight || 1);
    const pitch = (noseRelative - 0.4) * 120; // rough degrees

    // Simplified roll: angle between eye corners
    const dx = rightEye.x - leftEye.x;
    const dy = rightEye.y - leftEye.y;
    const roll = Math.atan2(dy, dx) * (180 / Math.PI);

    return { yaw, pitch, roll };
  } catch {
    return null;
  }
}

// ── Helper: Gaze offset ──────────────────────────
function computeGazeOffset(landmarks: any[]): { x: number; y: number } | null {
  try {
    // Use iris landmarks (468-477 in MediaPipe Face Mesh)
    // Left iris: 468-472, Right iris: 473-477
    const leftIris = landmarks[468];
    const rightIris = landmarks[473];
    const leftEyeInner = landmarks[133];
    const leftEyeOuter = landmarks[33];
    const rightEyeInner = landmarks[362];
    const rightEyeOuter = landmarks[263];

    if (!leftIris || !rightIris) return null;

    // Normalise iris position within eye bounds
    const leftEyeWidth = leftEyeOuter.x - leftEyeInner.x;
    const rightEyeWidth = rightEyeInner.x - rightEyeOuter.x;

    const leftGazeX = leftEyeWidth !== 0
      ? (leftIris.x - leftEyeInner.x) / leftEyeWidth * 2 - 1
      : 0;
    const rightGazeX = rightEyeWidth !== 0
      ? (rightIris.x - rightEyeOuter.x) / rightEyeWidth * 2 - 1
      : 0;

    return {
      x: (leftGazeX + rightGazeX) / 2,
      y: (leftIris.y - leftEyeInner.y + rightIris.y - rightEyeInner.y) / 2 * 10,
    };
  } catch {
    return null;
  }
}

// ── Helper: Cosine similarity ────────────────────
function cosineSimilarity(a: Float32Array, b: Float32Array): number {
  if (a.length !== b.length) return 0;
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dot / denom;
}

// ── Message Handler ──────────────────────────────
self.onmessage = async (event: MessageEvent<FaceWorkerInbound>) => {
  const msg = event.data;

  try {
    switch (msg.type) {
      case 'INIT': {
        // Lazy-load MediaPipe Face Landmarker
        const vision = await import('@mediapipe/tasks-vision');
        const { FaceLandmarker, FilesetResolver } = vision;

        const filesetResolver = await FilesetResolver.forVisionTasks(
          'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@latest/wasm'
        );

        faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
          baseOptions: {
            modelAssetPath: msg.modelPath || '/models/face_landmarker.task',
            delegate: 'GPU',
          },
          outputFaceBlendshapes: false,
          outputFacialTransformationMatrixes: false,
          runningMode: 'IMAGE',
          numFaces: 3, // Detect up to 3 faces
        });

        (self as any).postMessage({ type: 'READY' } as FaceWorkerOutbound);
        break;
      }

      case 'ANALYZE_FRAME': {
        if (!faceLandmarker) {
          (self as any).postMessage({
            type: 'ERROR',
            message: 'Face landmarker not initialized',
          } as FaceWorkerOutbound);
          return;
        }

        // Create ImageBitmap from ImageData for processing
        const bitmap = await createImageBitmap(msg.imageData);
        const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
        const ctx = canvas.getContext('2d')!;
        ctx.drawImage(bitmap, 0, 0);

        const result = faceLandmarker.detect(canvas);
        const faceCount = result.faceLandmarks?.length || 0;

        let headPose: FaceAnalysisResult['headPose'] = null;
        let gazeOffset: FaceAnalysisResult['gazeOffset'] = null;
        let earScore = 0.25;
        let landmarkCount = 0;

        if (faceCount > 0) {
          const landmarks = result.faceLandmarks[0];
          landmarkCount = landmarks.length;

          headPose = computeHeadPose(landmarks);
          gazeOffset = computeGazeOffset(landmarks);

          // Compute EAR
          const leftEAR = computeEAR(landmarks, LEFT_EYE);
          const rightEAR = computeEAR(landmarks, RIGHT_EYE);
          earScore = (leftEAR + rightEAR) / 2;

          // Track blinks
          const isBlink = earScore < 0.18;
          if (isBlink && !lastEarBelow) {
            blinkTimestamps.push(Date.now());
          }
          lastEarBelow = isBlink;
        }

        // Clean old blink timestamps (keep last 60s)
        const now = Date.now();
        blinkTimestamps = blinkTimestamps.filter(t => now - t < 60000);
        const blinkRate = blinkTimestamps.length; // blinks per minute

        // Identity verification (every 30s computed in main thread scheduler)
        let identityScore: number | null = null;
        // Note: face-api.js identity check happens on the main thread,
        // not in this worker, as face-api.js is not WASM-compatible in workers.

        const analysisResult: FaceAnalysisResult = {
          faceCount,
          headPose,
          gazeOffset,
          blinkRate,
          earScore,
          identityScore,
          landmarkCount,
        };

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId: msg.frameId,
          result: analysisResult,
        } as FaceWorkerOutbound);

        bitmap.close();
        break;
      }

      case 'SET_ENROLLMENT': {
        enrollmentDescriptor = msg.descriptor;
        break;
      }

      case 'SHUTDOWN': {
        if (faceLandmarker) {
          faceLandmarker.close();
          faceLandmarker = null;
        }
        self.close();
        break;
      }
    }
  } catch (error: any) {
    (self as any).postMessage({
      type: 'ERROR',
      message: error?.message || 'Unknown error in face_worker',
    } as FaceWorkerOutbound);
  }
};
