// FILE: workers/object_worker.ts
// Detect phones, books, laptops, second person silhouettes in video frame
// Uses TensorFlow.js COCO-SSD with ultra-fast lite_mobilenet_v2 backbone

export {};

// ── Message Types ────────────────────────────────

// INBOUND
type ObjectWorkerInbound =
  | { type: 'INIT'; modelPath?: string }
  | { type: 'ANALYZE_FRAME'; bitmap: ImageBitmap; frameId: number }
  | { type: 'ANALYZE_IMAGE_DATA'; imageData: ImageData; frameId: number }
  | { type: 'SHUTDOWN' };

// OUTBOUND
type ObjectWorkerOutbound =
  | { type: 'READY' }
  | { type: 'ERROR'; message: string }
  | { type: 'FRAME_RESULT'; frameId: number; detections: Detection[] };

interface Detection {
  class: string;               // 'cell phone', 'laptop', 'book', 'person'
  confidence: number;          // 0.0 - 1.0
  bbox: [number, number, number, number]; // [x, y, width, height] normalised
  isEdgePartial: boolean;      // true if bbox touches frame edge
}

let model: any = null;
let modelReady = false;
let offscreenCanvas: OffscreenCanvas | null = null;
let offscreenCtx: OffscreenCanvasRenderingContext2D | null = null;

// ── COCO-SSD Init Timeout ─────────────────────────────────────
// If model loading takes more than 20 s (CDN slow / network unavailable),
// resolve as READY anyway with model=null so the HUD shows "Clear" instead
// of being stuck on "Loading" forever.
const MODEL_LOAD_TIMEOUT_MS = 20000;

// ── Check if bbox touches frame edge ─────────────
function isEdge(bbox: [number, number, number, number], width: number, height: number): boolean {
  const [x, y, w, h] = bbox;
  const margin = 5;
  return (
    x <= margin ||
    y <= margin ||
    (x + w) >= (width - margin) ||
    (y + h) >= (height - margin)
  );
}

// ── Message Handler ──────────────────────────────
self.onmessage = async (event: MessageEvent<ObjectWorkerInbound>) => {
  const msg = event.data;

  try {
    switch (msg.type) {
      case 'INIT': {
        // Race model loading against a 20-second timeout so the HUD
        // never hangs on "Loading" in a demo / offline environment.
        const initWithTimeout = new Promise<void>(async (resolve) => {
          const timer = setTimeout(() => {
            console.warn('[object_worker] Model load timed out — resolving READY with null model (detections disabled)');
            resolve();
          }, MODEL_LOAD_TIMEOUT_MS);

          try {
            const tf = await import('@tensorflow/tfjs');
            const cocoSsd = await import('@tensorflow-models/coco-ssd');

            // Prefer webgl backend for hardware acceleration, fallback to cpu
            try {
              await tf.setBackend('webgl');
              await tf.ready();
            } catch {
              await tf.setBackend('cpu');
              await tf.ready();
            }

            // Fast lightweight MobileNet v2 backbone — loads from local /models/coco_ssd/
            // first, with fallback to Google storage CDN, and a 20s timeout safeguard.
            try {
              const loadOptions: any = { base: 'lite_mobilenet_v2' };
              if (msg.modelPath) {
                loadOptions.modelUrl = `${msg.modelPath}model.json`;
              }
              model = await cocoSsd.load(loadOptions);
            } catch (localErr) {
              console.warn('[object_worker] Local model load failed, falling back to CDN:', localErr);
              model = await cocoSsd.load({ base: 'lite_mobilenet_v2' });
            }
          } catch (e) {
            console.warn('[object_worker] COCO-SSD load error (continuing without object detection):', e);
            model = null;
          } finally {
            clearTimeout(timer);
            resolve();
          }
        });

        await initWithTimeout;
        modelReady = true;
        (self as any).postMessage({ type: 'READY' } as ObjectWorkerOutbound);
        break;
      }

      case 'ANALYZE_FRAME': {
        // If model never loaded (timeout / CDN failure), return empty detections
        // so the HUD shows "Clear" rather than hanging or erroring.
        if (!modelReady || !model) {
          (self as any).postMessage({
            type: 'FRAME_RESULT',
            frameId: msg.frameId,
            detections: [],
          } as ObjectWorkerOutbound);
          return;
        }

        const { bitmap, frameId } = msg;
        const width = bitmap.width;
        const height = bitmap.height;

        if (!offscreenCanvas || offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
          offscreenCanvas = new OffscreenCanvas(width, height);
          offscreenCtx = offscreenCanvas.getContext('2d')!;
        }

        offscreenCtx!.drawImage(bitmap, 0, 0);
        bitmap.close(); // clean up transferred ImageBitmap

        // Run detection on reused canvas
        const predictions = await model.detect(offscreenCanvas);

        const detections: Detection[] = [];
        for (const pred of predictions) {
          const className = pred.class.toLowerCase();
          const confidence = pred.score;
          const [bx, by, bw, bh] = pred.bbox;

          detections.push({
            class: className,
            confidence,
            bbox: [bx / width, by / height, bw / width, bh / height],
            isEdgePartial: isEdge(pred.bbox, width, height),
          });
        }

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId,
          detections,
        } as ObjectWorkerOutbound);
        break;
      }

      case 'ANALYZE_IMAGE_DATA': {
        if (!modelReady || !model) {
          (self as any).postMessage({
            type: 'FRAME_RESULT',
            frameId: msg.frameId,
            detections: [],
          } as ObjectWorkerOutbound);
          return;
        }
        const { imageData, frameId } = msg;
        const width = imageData.width;
        const height = imageData.height;

        if (!offscreenCanvas || offscreenCanvas.width !== width || offscreenCanvas.height !== height) {
          offscreenCanvas = new OffscreenCanvas(width, height);
          offscreenCtx = offscreenCanvas.getContext('2d')!;
        }
        offscreenCtx!.putImageData(imageData, 0, 0);

        const predictions = await model.detect(offscreenCanvas);
        const detections: Detection[] = predictions.map((pred: any) => ({
          class: pred.class.toLowerCase(),
          confidence: pred.score,
          bbox: [pred.bbox[0] / width, pred.bbox[1] / height, pred.bbox[2] / width, pred.bbox[3] / height],
          isEdgePartial: isEdge(pred.bbox, width, height),
        }));

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId,
          detections,
        } as ObjectWorkerOutbound);
        break;
      }

      case 'SHUTDOWN': {
        model = null;
        self.close();
        break;
      }
    }
  } catch (error: any) {
    (self as any).postMessage({
      type: 'ERROR',
      message: error?.message || 'Unknown error in object_worker',
    } as ObjectWorkerOutbound);
  }
};
