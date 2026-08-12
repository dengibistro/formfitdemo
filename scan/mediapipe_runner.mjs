// Zone 3: the only module in this project that touches the real
// @mediapipe/tasks-vision runtime. Wraps it so Zones 1-2
// (measurements.mjs, quality_gates.mjs) never need to know MediaPipe's
// specific shape — they receive plain {x,y,z,visibility} landmark arrays
// and a plain {maskFloat32Array, maskWidth, maskHeight} object, not
// MediaPipe's own classes.
//
// Verified against the real @mediapipe/tasks-vision@0.10.35 package before
// writing this — and worth recording *why* so carefully: two independent
// doc-lookup passes (an AI-summarized fetch of the guide page, then even an
// AI-summarized fetch of the raw .d.ts) both gave WRONG field names
// (`outputPoseSegmentationMasks`, `poseLandmarks`/`poseWorldLandmarks`/
// `poseSegmentationMasks`). Those actually belong to a *different*
// interface in the same file (HolisticLandmarkerOptions, which sits right
// next to PoseLandmarkerOptions and looks similar at a glance). Only a
// direct `grep` on the raw downloaded .d.ts text — not summarized by
// anything — surfaced the real fields below. Lesson: for a same-file
// naming collision like this, even "verified via the type file" isn't
// enough if a summarizing step sits in between; grep the raw text.
//
// Confirmed via raw grep on vision.d.ts:
//   PoseLandmarkerOptions.outputSegmentationMasks (boolean)
//   PoseLandmarkerResult.{landmarks, worldLandmarks, segmentationMasks}
//   Landmark / NormalizedLandmark: {x, y, z, visibility} only
//   MPMask: {width, height, getAsFloat32Array()}
// Confirmed via a live HTTP HEAD request (not just docs): the model URL
// below actually resolves (200, ~5.7MB).

import { FilesetResolver, PoseLandmarker } from "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/vision_bundle.mjs";

const WASM_BASE_PATH = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const MODEL_ASSET_PATH =
  "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task";

let landmarkerPromise = null;

/** Lazily creates a single shared PoseLandmarker (loading the WASM runtime
 * + model is expensive — do it once, not per frame/per capture). */
function getLandmarker() {
  if (!landmarkerPromise) {
    landmarkerPromise = FilesetResolver.forVisionTasks(WASM_BASE_PATH).then((vision) =>
      PoseLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: MODEL_ASSET_PATH, delegate: "GPU" },
        runningMode: "VIDEO",
        numPoses: 1,
        minPoseDetectionConfidence: 0.5,
        minPosePresenceConfidence: 0.5,
        minTrackingConfidence: 0.5,
        outputSegmentationMasks: true,
      }),
    );
  }
  return landmarkerPromise;
}

/**
 * Zone 5: kicks off the WASM+model download without needing a video frame
 * yet — call this from a splash/loading screen so the ~5.7MB model is
 * already warm by the time the user reaches the camera step. Without this,
 * the first real `detectPoseInVideoFrame` call pays the full download cost
 * with zero UI feedback, which read as a frozen page during real-device
 * testing (see PRODUCT_ROADMAP_NOTES.md). Safe to call more than once —
 * `getLandmarker()` caches the one in-flight/completed promise.
 */
export function preloadPoseLandmarker() {
  return getLandmarker();
}

/**
 * Runs detection on one video frame. Returns null if no person was
 * detected at all (caller should treat this the same as a framing
 * failure). Repackaged into plain objects/arrays — never hands MediaPipe's
 * own result type to callers, so Zones 1-2 stay MediaPipe-agnostic.
 */
export async function detectPoseInVideoFrame(videoElement, timestampMs) {
  const landmarker = await getLandmarker();
  const result = landmarker.detectForVideo(videoElement, timestampMs);
  if (!result.landmarks || result.landmarks.length === 0) return null;
  return {
    landmarks: result.landmarks[0],
    worldLandmarks: result.worldLandmarks[0],
    segmentationMask: result.segmentationMasks ? result.segmentationMasks[0] : null,
  };
}

/** Converts a MediaPipe segmentation mask into the plain shape Zone 1's
 * `computeChestDepthMm` expects — keeps `MPMask` itself out of Zone 1. */
export function maskToPlainData(mpMask) {
  return {
    maskFloat32Array: mpMask.getAsFloat32Array(),
    maskWidth: mpMask.width,
    maskHeight: mpMask.height,
  };
}

// ---------------------------------------------------------------------------
// Average frame luminance (0..1) — feeds Zone 2's `isLightingOk`. Sampled on
// a small offscreen canvas (not full resolution) since only a rough average
// is needed; keeps this cheap enough to run every frame.
// ---------------------------------------------------------------------------

const LUMINANCE_SAMPLE_SIZE = 32;
let luminanceCanvas = null;
let luminanceCtx = null;

export function estimateAverageLuminance(videoElement) {
  if (!luminanceCanvas) {
    luminanceCanvas = document.createElement("canvas");
    luminanceCanvas.width = LUMINANCE_SAMPLE_SIZE;
    luminanceCanvas.height = LUMINANCE_SAMPLE_SIZE;
    luminanceCtx = luminanceCanvas.getContext("2d", { willReadFrequently: true });
  }
  luminanceCtx.drawImage(videoElement, 0, 0, LUMINANCE_SAMPLE_SIZE, LUMINANCE_SAMPLE_SIZE);
  const { data } = luminanceCtx.getImageData(0, 0, LUMINANCE_SAMPLE_SIZE, LUMINANCE_SAMPLE_SIZE);
  let total = 0;
  const pixelCount = LUMINANCE_SAMPLE_SIZE * LUMINANCE_SAMPLE_SIZE;
  for (let i = 0; i < data.length; i += 4) {
    total += 0.299 * data[i] + 0.587 * data[i + 1] + 0.114 * data[i + 2]; // standard perceptual weighting
  }
  return total / pixelCount / 255;
}

// ---------------------------------------------------------------------------
// Camera access. Rear camera ('environment') is the product default (more
// accurate, per PRODUCT_ROADMAP_NOTES.md); front ('user') is opt-in.
// getUserMedia requires a secure context (https, or localhost) — a plain
// file:// page will not be granted camera access by the browser.
// ---------------------------------------------------------------------------

export async function startCamera(videoElement, facingMode = "environment") {
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
    audio: false,
  });
  videoElement.srcObject = stream;
  await videoElement.play();
  return stream;
}

export function stopCamera(stream) {
  for (const track of stream.getTracks()) track.stop();
}
