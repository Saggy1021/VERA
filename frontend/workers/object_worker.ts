// FILE: workers/object_worker.ts
// Detect phones, books, laptops, second person silhouettes in video frame
// Uses TensorFlow.js COCO-SSD (MobileNet v2 backbone)

// ── Message Types ────────────────────────────────

// INBOUND
type ObjectWorkerInbound =
  | { type: 'INIT'; modelPath: string }
  | { type: 'ANALYZE_FRAME'; imageData: ImageData; frameId: number }
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
  isEdgePartial: boolean;      // true if bbox touches frame edge (lower conf threshold)
}

// OBJECT CLASSES TO FLAG:
// 'cell phone' confidence > 0.55  (lower threshold if isEdgePartial)
// 'laptop'     confidence > 0.60  (candidate's own laptop OK — flag secondary screen)
// 'book'       confidence > 0.65
// 'person'     count > 1          (multiple people = multiple_faces trigger)

const FLAGGED_CLASSES: Record<string, number> = {
  'cell phone': 0.55,
  'laptop': 0.60,
  'book': 0.65,
  'person': 0.40, // Lower threshold, we care about count > 1
};

let model: any = null;

// ── Check if bbox touches frame edge ─────────────
function isEdge(bbox: [number, number, number, number], width: number, height: number): boolean {
  const [x, y, w, h] = bbox;
  const margin = 5; // pixels
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
        // Lazy-load TensorFlow.js and COCO-SSD
        const tf = await import('@tensorflow/tfjs');
        const cocoSsd = await import('@tensorflow-models/coco-ssd');

        // Set backend to webgl for GPU acceleration
        await tf.setBackend('webgl');
        await tf.ready();

        model = await cocoSsd.load({
          base: 'mobilenet_v2',
        });

        (self as any).postMessage({ type: 'READY' } as ObjectWorkerOutbound);
        break;
      }

      case 'ANALYZE_FRAME': {
        if (!model) {
          (self as any).postMessage({
            type: 'ERROR',
            message: 'COCO-SSD model not initialized',
          } as ObjectWorkerOutbound);
          return;
        }

        const { imageData, frameId } = msg;
        const width = imageData.width;
        const height = imageData.height;

        // Create canvas for TF.js processing
        const canvas = new OffscreenCanvas(width, height);
        const ctx = canvas.getContext('2d')!;
        ctx.putImageData(imageData, 0, 0);

        // Run detection
        const predictions = await model.detect(canvas);

        // Filter and map to our Detection interface
        const detections: Detection[] = [];
        for (const pred of predictions) {
          const className = pred.class.toLowerCase();
          const threshold = FLAGGED_CLASSES[className];

          if (threshold !== undefined && pred.score >= threshold * 0.7) {
            // Raw bbox from COCO-SSD: [x, y, width, height] in pixels
            const bbox: [number, number, number, number] = [
              pred.bbox[0] / width,
              pred.bbox[1] / height,
              pred.bbox[2] / width,
              pred.bbox[3] / height,
            ];

            const edgePartial = isEdge(
              [pred.bbox[0], pred.bbox[1], pred.bbox[2], pred.bbox[3]],
              width,
              height
            );

            detections.push({
              class: className,
              confidence: pred.score,
              bbox,
              isEdgePartial: edgePartial,
            });
          }
        }

        (self as any).postMessage({
          type: 'FRAME_RESULT',
          frameId,
          detections,
        } as ObjectWorkerOutbound);
        break;
      }

      case 'SHUTDOWN': {
        if (model) {
          model = null;
        }
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
