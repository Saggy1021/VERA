// FILE: workers/face_worker.ts
// Face presence, head pose, gaze, blink rate, multi-face, identity verification
// Uses MediaPipe Face Landmarker WASM with local files & CPU fallback

export {};

// ── Message Types ────────────────────────────────

// INBOUND (main thread → worker)
type FaceWorkerInbound =
  | { type: 'INIT'; modelPath?: string }
  | { type: 'ANALYZE_FRAME'; bitmap: ImageBitmap; frameId: number; timestamp: number }
  | { type: 'ANALYZE_IMAGE_DATA'; imageData: ImageData; frameId: number; timestamp: number }
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
  expression: 'neutral' | 'stressed' | 'talking' | 'smiling';
  lipMovement: boolean;
  marScore: number;
  faceDescriptor?: number[];
}

// ── Worker State ─────────────────────────────────
let faceLandmarker: any = null;
let enrollmentDescriptor: Float32Array | null = null;
let blinkTimestamps: number[] = [];
let lastEarBelow: boolean = false;
let marHistory: number[] = [];
let offscreenCanvas: OffscreenCanvas | null = null;
let offscreenCtx: OffscreenCanvasRenderingContext2D | null = null;
let lastVideoTimestamp = 0;

// Stable landmarks for 128-dim normalized geometric face signature
const SIGNATURE_LANDMARKS = [
  1, 2, 4, 5, 6, 10, 33, 61, 70, 105, 107, 133, 152, 168, 197, 234,
  263, 291, 300, 334, 336, 362, 454, 13, 14, 78, 308, 19, 94, 123,
  352, 356, 127, 226, 247, 446, 467, 109, 338, 151, 9, 8
];

function computeGeometricFaceDescriptor(landmarks: any[]): number[] {
  const nose = landmarks[1] || { x: 0.5, y: 0.5, z: 0 };
  const leftEyeOuter = landmarks[33] || { x: 0.4, y: 0.4, z: 0 };
  const rightEyeOuter = landmarks[263] || { x: 0.6, y: 0.4, z: 0 };

  const iod = Math.sqrt(
    (rightEyeOuter.x - leftEyeOuter.x) ** 2 +
    (rightEyeOuter.y - leftEyeOuter.y) ** 2 +
    ((rightEyeOuter.z || 0) - (leftEyeOuter.z || 0)) ** 2
  ) || 0.1;

  const descriptor: number[] = [];
  for (const idx of SIGNATURE_LANDMARKS) {
    const pt = landmarks[idx] || nose;
    descriptor.push((pt.x - nose.x) / iod);
    descriptor.push((pt.y - nose.y) / iod);
    descriptor.push(((pt.z || 0) - (nose.z || 0)) / iod);
  }

  // 126 coordinates + 2 morphology ratios = 128 floats
  const chin = landmarks[152] || nose;
  const leftMouth = landmarks[61] || nose;
  const rightMouth = landmarks[291] || nose;
  const faceHeight = Math.abs(chin.y - ((leftEyeOuter.y + rightEyeOuter.y) / 2)) / iod;
  const mouthWidth = Math.sqrt((rightMouth.x - leftMouth.x) ** 2 + (rightMouth.y - leftMouth.y) ** 2) / iod;
  descriptor.push(faceHeight);
  descriptor.push(mouthWidth);

  // Normalize to unit vector
  let sumSq = 0;
  for (let i = 0; i < descriptor.length; i++) sumSq += descriptor[i] * descriptor[i];
  const mag = Math.sqrt(sumSq) || 1;
  return descriptor.map(v => v / mag);
}

function computeCosineSimilarity(a: Float32Array | number[], b: Float32Array | number[]): number {
  let dot = 0;
  let normA = 0;
  let normB = 0;
  const len = Math.min(a.length, b.length);
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  if (normA === 0 || normB === 0) return 0;
  const sim = dot / (Math.sqrt(normA) * Math.sqrt(normB));
  return Math.max(0, Math.min(1, sim));
}

// ── Helper: Eye Aspect Ratio ─────────────────────
function computeEAR(landmarks: any[], eyeIndices: number[]): number {
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
    return 0.25;
  }
}

// MediaPipe eye landmark indices
const LEFT_EYE = [33, 160, 158, 133, 153, 144];
const RIGHT_EYE = [362, 385, 387, 263, 373, 380];

// ── Helper: Head Pose from landmarks ─────────────
function computeHeadPose(landmarks: any[]): { yaw: number; pitch: number; roll: number } | null {
  try {
    const noseTip = landmarks[1];
    const chin = landmarks[152];
    const leftEye = landmarks[33];
    const rightEye = landmarks[263];

    const eyeMidX = (leftEye.x + rightEye.x) / 2;
    const yaw = (noseTip.x - eyeMidX) * 180;

    const eyeMidY = (leftEye.y + rightEye.y) / 2;
    const faceHeight = chin.y - eyeMidY;
    const noseRelative = (noseTip.y - eyeMidY) / (faceHeight || 1);
    const pitch = (noseRelative - 0.4) * 120;

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
    const leftIris = landmarks[468];
    const rightIris = landmarks[473];
    const leftEyeInner = landmarks[133];
    const leftEyeOuter = landmarks[33];
    const rightEyeInner = landmarks[362];
    const rightEyeOuter = landmarks[263];

    if (!leftIris || !rightIris) return null;

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

// ── Message Handler ──────────────────────────────
self.onmessage = async (event: MessageEvent<FaceWorkerInbound>) => {
  const msg = event.data;

  try {
    switch (msg.type) {
      case 'INIT': {
        const vision = await import('@mediapipe/tasks-vision');
        const { FaceLandmarker, FilesetResolver } = vision;

        // Try local WASM first, fallback to CDN
        let filesetResolver;
        try {
          filesetResolver = await FilesetResolver.forVisionTasks('/models/wasm');
        } catch {
          console.warn('[FaceWorker] Local WASM resolver failed, falling back to CDN');
          filesetResolver = await FilesetResolver.forVisionTasks(
            'https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm'
          );
        }

        const modelPath = msg.modelPath || '/models/face_landmarker.task';

        // Try GPU delegate first, fallback to CPU if GPU not supported
        try {
          faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: modelPath,
              delegate: 'GPU',
            },
            outputFaceBlendshapes: true,
            outputFacialTransformationMatrixes: false,
            runningMode: 'VIDEO',
            numFaces: 3,
          });
        } catch (gpuErr) {
          console.warn('[FaceWorker] GPU delegate failed, falling back to CPU:', gpuErr);
          faceLandmarker = await FaceLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: modelPath,
              delegate: 'CPU',
            },
            outputFaceBlendshapes: true,
            outputFacialTransformationMatrixes: false,
            runningMode: 'VIDEO',
            numFaces: 3,
          });
        }

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

        const { bitmap, frameId } = msg;
        const width = bitmap.width;
        const height = bitmap.height;

        // Reuse persistent canvas
        if (!offscreenCanvas || offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
          offscreenCanvas = new OffscreenCanvas(width, height);
          offscreenCtx = offscreenCanvas.getContext('2d')!;
        }

        offscreenCtx!.drawImage(bitmap, 0, 0);
        bitmap.close(); // zero-copy transfer cleanup

        // Monotonic timestamp required by detectForVideo
        let timestamp = msg.timestamp || performance.now();
        if (timestamp <= lastVideoTimestamp) {
          timestamp = lastVideoTimestamp + 1;
        }
        lastVideoTimestamp = timestamp;

        const result = faceLandmarker.detectForVideo(offscreenCanvas, timestamp);
        const faceCount = result.faceLandmarks?.length || 0;

        let headPose: FaceAnalysisResult['headPose'] = null;
        let gazeOffset: FaceAnalysisResult['gazeOffset'] = null;
        let earScore = 0.25;
        let landmarkCount = 0;
        let expression: FaceAnalysisResult['expression'] = 'neutral';
        let lipMovement = false;
        let marScore = 0;
        let faceDescriptor: number[] | undefined;
        let identityScore: number | null = null;

        if (faceCount > 0) {
          const landmarks = result.faceLandmarks[0];
          landmarkCount = landmarks.length;

          headPose = computeHeadPose(landmarks);
          gazeOffset = computeGazeOffset(landmarks);

          const leftEAR = computeEAR(landmarks, LEFT_EYE);
          const rightEAR = computeEAR(landmarks, RIGHT_EYE);
          earScore = (leftEAR + rightEAR) / 2;

          const isBlink = earScore < 0.18;
          if (isBlink && !lastEarBelow) {
            blinkTimestamps.push(Date.now());
          }
          lastEarBelow = isBlink;

          // Compute 128-dim geometric face descriptor
          faceDescriptor = computeGeometricFaceDescriptor(landmarks);
          if (enrollmentDescriptor) {
            identityScore = Math.round(computeCosineSimilarity(faceDescriptor, enrollmentDescriptor) * 100) / 100;
          }

          // Mouth Aspect Ratio (MAR) from inner lips: 13 (upper), 14 (lower), 78 (left), 308 (right)
          const dist = (a: any, b: any) => Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
          const vertLip = dist(landmarks[13], landmarks[14]);
          const horizLip = dist(landmarks[78], landmarks[308]);
          marScore = horizLip > 0 ? vertLip / horizLip : 0;

          // Extract blendshapes
          const blendshapes: Record<string, number> = {};
          if (result.faceBlendshapes && result.faceBlendshapes.length > 0) {
            const categories = result.faceBlendshapes[0].categories || [];
            for (const c of categories) {
              blendshapes[c.categoryName] = c.score;
            }
          }

          const jawOpen = blendshapes['jawOpen'] || (marScore > 0.25 ? 0.35 : 0);
          const browDownLeft = blendshapes['browDownLeft'] || 0;
          const browDownRight = blendshapes['browDownRight'] || 0;
          const mouthSmileLeft = blendshapes['mouthSmileLeft'] || 0;
          const mouthSmileRight = blendshapes['mouthSmileRight'] || 0;

          if (mouthSmileLeft > 0.4 || mouthSmileRight > 0.4) {
            expression = 'smiling';
          } else if (browDownLeft > 0.35 || browDownRight > 0.35) {
            expression = 'stressed';
          } else if (jawOpen > 0.3 || marScore > 0.28) {
            expression = 'talking';
          } else {
            expression = 'neutral';
          }

          // Track rolling lip-motion variance over ~1.5s (last 8 frames)
          marHistory.push(marScore + jawOpen * 0.5);
          if (marHistory.length > 8) marHistory.shift();

          if (marHistory.length >= 4) {
            const mean = marHistory.reduce((a, b) => a + b, 0) / marHistory.length;
            const variance = marHistory.reduce((a, b) => a + (b - mean) ** 2, 0) / marHistory.length;
            const maxDiff = Math.max(...marHistory) - Math.min(...marHistory);
            lipMovement = variance > 0.0025 || maxDiff > 0.1 || jawOpen > 0.25 || expression === 'talking';
          }
        }

        const now = Date.now();
        blinkTimestamps = blinkTimestamps.filter(t => now - t < 60000);
        const blinkRate = blinkTimestamps.length;

        const analysisResult: FaceAnalysisResult = {
          faceCount,
          headPose,
          gazeOffset,
          blinkRate,
          earScore,
          identityScore,
          landmarkCount,
          expression,
          lipMovement,
          marScore,
          faceDescriptor,
        };

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId,
          result: analysisResult,
        } as FaceWorkerOutbound);
        break;
      }

      case 'ANALYZE_IMAGE_DATA': {
        // Fallback if browser doesn't support ImageBitmap transfer
        if (!faceLandmarker) return;
        const { imageData, frameId } = msg;
        const width = imageData.width;
        const height = imageData.height;

        if (!offscreenCanvas || offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
          offscreenCanvas = new OffscreenCanvas(width, height);
          offscreenCtx = offscreenCanvas.getContext('2d')!;
        }
        offscreenCtx!.putImageData(imageData, 0, 0);

        let timestamp = msg.timestamp || performance.now();
        if (timestamp <= lastVideoTimestamp) {
          timestamp = lastVideoTimestamp + 1;
        }
        lastVideoTimestamp = timestamp;

        const result = faceLandmarker.detectForVideo(offscreenCanvas, timestamp);
        const faceCount = result.faceLandmarks?.length || 0;
        let headPose = null;
        let gazeOffset = null;
        let earScore = 0.25;

        if (faceCount > 0) {
          const landmarks = result.faceLandmarks[0];
          headPose = computeHeadPose(landmarks);
          gazeOffset = computeGazeOffset(landmarks);
          const leftEAR = computeEAR(landmarks, LEFT_EYE);
          const rightEAR = computeEAR(landmarks, RIGHT_EYE);
          earScore = (leftEAR + rightEAR) / 2;
        }

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId,
          result: {
            faceCount,
            headPose,
            gazeOffset,
            blinkRate: 15,
            earScore,
            identityScore: null,
            landmarkCount: faceCount > 0 ? result.faceLandmarks[0].length : 0,
            expression: 'neutral',
            lipMovement: false,
            marScore: 0,
          },
        } as FaceWorkerOutbound);
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
