// Zone 1: calibration + anthropometric measurement computation.
//
// Pure computation over already-captured MediaPipe Tasks Vision
// PoseLandmarker output — no camera, no UI, no live capture loop here (that's
// later zones). Verified against the real @mediapipe/tasks-vision v0.10.35
// type definitions via a raw grep on the downloaded .d.ts (not recalled from
// training, and not just an AI-summarized doc fetch either — see
// scan/mediapipe_runner.mjs's docstring for why that mattered here):
// PoseLandmarkerResult = { landmarks, worldLandmarks, segmentationMasks };
// each Landmark/NormalizedLandmark has only { x, y, z, visibility } — no
// separate `presence` field despite what the general docs page implies.
// World landmarks are real-world *meters*, hip-centered, but not calibrated
// to any specific person's actual size — that calibration is this module's
// job. This module takes plain arrays (already unwrapped from index [0] of
// the multi-person result) — it never touches MediaPipe's own types
// directly, that's scan/mediapipe_runner.mjs's job.
//
// Design choice, REVISED 2026-07-08 after first real-device testing: every
// length here uses only the x/y components of world landmarks — z (depth)
// is deliberately dropped. Originally this used full 3D Euclidean distance
// (see git history / PRODUCT_ROADMAP_NOTES.md for the original rationale),
// on the theory that 3D would be more robust to perspective than a flat
// pixel-ratio approach. Real capture data showed the opposite in practice:
// z came back noisy enough to produce a ~2x-wrong calibration factor, wildly
// asymmetric left/right leg lengths, and (in quality_gates.mjs) a rotation
// check that never fired for a true side profile — monocular depth
// estimation is the least reliable part of any single-camera pose model,
// and for the poses this protocol actually uses, the real anatomical
// measurement is dominated by x/y anyway: a person facing the camera has
// their limbs almost entirely in the camera's x/y plane, and a person
// rotated 90° to face sideways still keeps their spine vertical in the
// room — i.e. still aligned with the camera's y-axis regardless of which
// way their body is turned. Including z was adding noise, not signal, for
// every measurement this module actually needs. Kept the calibration
// ear-to-ankle proxy (ankle, not heel — heel is a softer, less reliably
// tracked landmark) but same 2D-only distance.

export const POSE_LANDMARK = Object.freeze({
  NOSE: 0,
  LEFT_EYE_INNER: 1, LEFT_EYE: 2, LEFT_EYE_OUTER: 3,
  RIGHT_EYE_INNER: 4, RIGHT_EYE: 5, RIGHT_EYE_OUTER: 6,
  LEFT_EAR: 7, RIGHT_EAR: 8,
  MOUTH_LEFT: 9, MOUTH_RIGHT: 10,
  LEFT_SHOULDER: 11, RIGHT_SHOULDER: 12,
  LEFT_ELBOW: 13, RIGHT_ELBOW: 14,
  LEFT_WRIST: 15, RIGHT_WRIST: 16,
  LEFT_PINKY: 17, RIGHT_PINKY: 18,
  LEFT_INDEX: 19, RIGHT_INDEX: 20,
  LEFT_THUMB: 21, RIGHT_THUMB: 22,
  LEFT_HIP: 23, RIGHT_HIP: 24,
  LEFT_KNEE: 25, RIGHT_KNEE: 26,
  LEFT_ANKLE: 27, RIGHT_ANKLE: 28,
  LEFT_HEEL: 29, RIGHT_HEEL: 30,
  LEFT_FOOT_INDEX: 31, RIGHT_FOOT_INDEX: 32,
});

// ---------------------------------------------------------------------------
// Generic landmark geometry — no MediaPipe-specific knowledge here.
// Deliberately 2D (x/y only, z ignored) — see module docstring above.
// ---------------------------------------------------------------------------

function midpoint(a, b) {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

function distance2D(a, b) {
  const dx = a.x - b.x, dy = a.y - b.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** 2D (x/y-only) distance between two world landmarks, in mm, after
 * applying the per-session calibration factor. `worldLandmarks` are in
 * meters. */
function distanceMm(worldLandmarks, indexA, indexB, calibrationFactor) {
  const meters = distance2D(worldLandmarks[indexA], worldLandmarks[indexB]);
  return meters * 1000 * calibrationFactor;
}

// ---------------------------------------------------------------------------
// Calibration: derive one scalar correction factor from the front-standing
// capture, comparing MediaPipe's own (uncalibrated) height estimate against
// the user's self-entered height. Reused for every other measurement across
// all three captures — see PRODUCT_ROADMAP_NOTES.md's "calibration
// algorithm" section for the full rationale (rejected a naive 2D
// pixel-ratio approach; rejected a physical reference object for precision).
// ---------------------------------------------------------------------------

/** Ear-to-ankle span as a fraction of full standing height: ear (tragion)
 * sits at ~0.93·H, the ankle (lateral malleolus) at ~0.04·H — standard
 * anthropometric proportions, a population ratio rather than a
 * per-person measurement.
 *
 * REVISED 2026-09-28: calibration used to divide the entered FULL height
 * by the model's ear-to-ankle span directly, which silently stretched that
 * span to full height and inflated every derived segment (F, Ti, A, BAW,
 * Cd, T) by ~1/0.89 ≈ +12%. The ratio now compares like with like. */
export const EAR_TO_ANKLE_FRACTION_OF_HEIGHT = 0.89;

/** MediaPipe's own uncalibrated ear-midpoint to ankle-midpoint span, in mm
 * (ankle, not heel — heel proved less reliably tracked in real captures;
 * see module docstring). Shorter than true standing height — see
 * EAR_TO_ANKLE_FRACTION_OF_HEIGHT for how calibration accounts for that. */
export function estimateModelHeightMm(frontWorldLandmarks) {
  const L = POSE_LANDMARK;
  const earMid = midpoint(frontWorldLandmarks[L.LEFT_EAR], frontWorldLandmarks[L.RIGHT_EAR]);
  const ankleMid = midpoint(frontWorldLandmarks[L.LEFT_ANKLE], frontWorldLandmarks[L.RIGHT_ANKLE]);
  return distance2D(earMid, ankleMid) * 1000;
}

/** expected ear-to-ankle span (entered H × EAR_TO_ANKLE_FRACTION_OF_HEIGHT)
 * / model ear-to-ankle span — the single per-session scale correction,
 * derived once from the front-standing capture and reused for every other
 * segment across all three captures (see module docstring). */
export function computeCalibrationFactor(frontWorldLandmarks, userHeightMm) {
  if (!(userHeightMm > 0)) {
    throw new Error("userHeightMm must be a positive number");
  }
  const modelHeightMm = estimateModelHeightMm(frontWorldLandmarks);
  if (!(modelHeightMm > 0)) {
    throw new Error("could not estimate a model height from the front capture (degenerate landmarks)");
  }
  return (userHeightMm * EAR_TO_ANKLE_FRACTION_OF_HEIGHT) / modelHeightMm;
}

// ---------------------------------------------------------------------------
// Front-standing capture -> F (left/right), Ti (left/right), A (left/right),
// BAW. Arm length is summed shoulder->elbow + elbow->wrist (the limb's own
// path), not a straight shoulder-to-wrist chord — matches models.py's
// LimbDecomposition docstring, which anticipates A being captured as one
// combined segment (not humerus/forearm separately).
// ---------------------------------------------------------------------------

export function computeFrontMeasurementsMm(frontWorldLandmarks, calibrationFactor) {
  const L = POSE_LANDMARK;
  const w = frontWorldLandmarks;
  return {
    femur_L_mm: distanceMm(w, L.LEFT_HIP, L.LEFT_KNEE, calibrationFactor),
    femur_R_mm: distanceMm(w, L.RIGHT_HIP, L.RIGHT_KNEE, calibrationFactor),
    tibia_L_mm: distanceMm(w, L.LEFT_KNEE, L.LEFT_ANKLE, calibrationFactor),
    tibia_R_mm: distanceMm(w, L.RIGHT_KNEE, L.RIGHT_ANKLE, calibrationFactor),
    arm_L_mm:
      distanceMm(w, L.LEFT_SHOULDER, L.LEFT_ELBOW, calibrationFactor) +
      distanceMm(w, L.LEFT_ELBOW, L.LEFT_WRIST, calibrationFactor),
    arm_R_mm:
      distanceMm(w, L.RIGHT_SHOULDER, L.RIGHT_ELBOW, calibrationFactor) +
      distanceMm(w, L.RIGHT_ELBOW, L.RIGHT_WRIST, calibrationFactor),
    biacromial_width_mm: distanceMm(w, L.LEFT_SHOULDER, L.RIGHT_SHOULDER, calibrationFactor),
  };
}

// ---------------------------------------------------------------------------
// Side-seated capture -> T (sitting height).
//
// What every seated machine actually needs is the shoulder (GH) joint's
// height above the seat — the engine computes it as k_sh·T (constants.md:
// k_sh = "GH-joint height above seat ÷ sitting height", with T the standard
// seat-to-crown sitting height). So measure that shoulder height directly
// (shoulder-midpoint to hip-midpoint, plus the hip joint's fixed offset
// above the seat surface) and express it back as T = height / k_sh — the
// engine's k_sh·T then recovers exactly what was measured.
//
// REVISED 2026-09-28: this used to return ear-midpoint to hip-midpoint as T
// directly. That's a different segment (~0.40·H, not the ~0.52·H seat-to-
// crown height k_sh is defined against), so every seat target came out
// several holes too high — nearly every user landed on pin 1 / CLAMPED_HIGH.
// ---------------------------------------------------------------------------

/** constants.md `k_sh` — must stay in sync with models.py's GlobalCoefficients. */
export const K_SH = 0.63;

/** Seated hip joint centre above the (compressed) seat surface, mm —
 * anthropometric population value, not measured per person; pose landmarks
 * have no point on the seat itself to measure it from. */
export const HIP_JOINT_ABOVE_SEAT_MM = 90;

export function computeShoulderHeightAboveSeatMm(seatedWorldLandmarks, calibrationFactor) {
  const L = POSE_LANDMARK;
  const shoulderMid = midpoint(seatedWorldLandmarks[L.LEFT_SHOULDER], seatedWorldLandmarks[L.RIGHT_SHOULDER]);
  const hipMid = midpoint(seatedWorldLandmarks[L.LEFT_HIP], seatedWorldLandmarks[L.RIGHT_HIP]);
  return distance2D(shoulderMid, hipMid) * 1000 * calibrationFactor + HIP_JOINT_ABOVE_SEAT_MM;
}

export function computeSittingHeightMm(seatedWorldLandmarks, calibrationFactor) {
  return computeShoulderHeightAboveSeatMm(seatedWorldLandmarks, calibrationFactor) / K_SH;
}

// ---------------------------------------------------------------------------
// Side-standing capture -> Cd (chest depth). Genuinely the hardest of the 7:
// no pair of pose landmarks represents "front of torso" vs "back of torso"
// (joints sit on the body's central axis, not its surface), so this can't be
// a landmark-to-landmark distance like everything else. Approach: measure
// the segmentation mask's horizontal pixel extent at chest height (in a true
// side-profile shot, the body's front-back axis maps onto the image's
// horizontal axis) — then convert that pixel width to mm using a per-frame
// pixel<->model-meter ratio derived from this same frame's own shoulder-hip
// distance (known in both world-landmark meters and normalized-image
// pixels), and finally apply the same global calibrationFactor as every
// other segment for consistency.
//
// Flagged explicitly (per PRODUCT_ROADMAP_NOTES.md): this is the project's
// own documented lower-confidence measurement, not on equal footing with
// the clean joint-to-joint distances above — callers should inflate its σ
// accordingly (see segmentConfidenceSigmaMm's cdConfidencePenalty).
// ---------------------------------------------------------------------------

/** Widest contiguous run isn't required — just first-to-last foreground
 * pixel on the row, which is what "body thickness at this height" means. */
export function measureMaskRowWidthPx(maskFloat32Array, width, height, row, threshold = 0.5) {
  const clampedRow = Math.min(Math.max(Math.round(row), 0), height - 1);
  let first = -1;
  let last = -1;
  const rowOffset = clampedRow * width;
  for (let x = 0; x < width; x++) {
    if (maskFloat32Array[rowOffset + x] >= threshold) {
      if (first === -1) first = x;
      last = x;
    }
  }
  if (first === -1) return null; // no foreground pixel on this row at all
  return last - first + 1;
}

/**
 * @param frame.worldLandmarks - worldLandmarks[0] for the side-standing capture
 * @param frame.normalizedLandmarks - landmarks[0] for the same capture (image-normalized [0,1])
 * @param frame.maskFloat32Array - segmentationMask.getAsFloat32Array()
 * @param frame.maskWidth - segmentationMask.width
 * @param frame.maskHeight - segmentationMask.height
 */
export function computeChestDepthMm(frame, calibrationFactor) {
  const L = POSE_LANDMARK;
  const w = frame.worldLandmarks;
  const n = frame.normalizedLandmarks;

  const shoulderMidWorld = midpoint(w[L.LEFT_SHOULDER], w[L.RIGHT_SHOULDER]);
  const hipMidWorld = midpoint(w[L.LEFT_HIP], w[L.RIGHT_HIP]);
  const torsoModelMeters = distance2D(shoulderMidWorld, hipMidWorld);

  const shoulderMid2D = midpoint(n[L.LEFT_SHOULDER], n[L.RIGHT_SHOULDER]);
  const hipMid2D = midpoint(n[L.LEFT_HIP], n[L.RIGHT_HIP]);
  const torsoPixels = Math.hypot(
    (shoulderMid2D.x - hipMid2D.x) * frame.maskWidth,
    (shoulderMid2D.y - hipMid2D.y) * frame.maskHeight,
  );
  if (!(torsoPixels > 0) || !(torsoModelMeters > 0)) {
    return null; // degenerate frame — caller should treat as an unmeasurable capture, prompt a retry
  }
  const modelMetersPerPixel = torsoModelMeters / torsoPixels;

  const chestRow = shoulderMid2D.y * frame.maskHeight;
  const rowWidthPx = measureMaskRowWidthPx(frame.maskFloat32Array, frame.maskWidth, frame.maskHeight, chestRow);
  if (rowWidthPx === null) return null;

  const chestDepthModelMeters = rowWidthPx * modelMetersPerPixel;
  return chestDepthModelMeters * 1000 * calibrationFactor;
}

// ---------------------------------------------------------------------------
// Dynamic per-segment confidence (extends ScanErrorConstants with a real,
// non-hardcoded σ per scan — see PRODUCT_ROADMAP_NOTES.md). Inflates a base
// σ (mirroring models.py's ScanErrorConstants defaults) based on the actual
// visibility scores of the landmarks that defined this segment. Linear ramp
// below a visibility floor — deliberately simple/tunable, not fixed by any
// spec, same discipline as the illustrative FrameConstants elsewhere in this
// project: explicit placeholder, not hidden as if it were exact.
// ---------------------------------------------------------------------------

const HIGH_VISIBILITY_FLOOR = 0.9;
const MAX_INFLATION_MULTIPLIER = 4;

export function segmentConfidenceSigmaMm(baseSigmaMm, involvedLandmarks) {
  const minVisibility = Math.min(...involvedLandmarks.map((l) => l.visibility));
  if (minVisibility >= HIGH_VISIBILITY_FLOOR) return baseSigmaMm;
  const clampedVisibility = Math.max(minVisibility, 0);
  const inflation = 1 + (HIGH_VISIBILITY_FLOOR - clampedVisibility) * MAX_INFLATION_MULTIPLIER;
  return baseSigmaMm * inflation;
}

/** Cd's own technique (mask-width, not landmark-distance) is inherently
 * less precise regardless of visibility — flagged explicitly in
 * PRODUCT_ROADMAP_NOTES.md as the project's accepted lower-confidence
 * input. Applied on top of (not instead of) the visibility-based inflation. */
export const CD_CONFIDENCE_PENALTY_MULTIPLIER = 1.5;

/** constants.md / models.py ScanErrorConstants defaults, mm — the σ of each
 * segment when every landmark behind it was clearly seen. */
export const BASE_SIGMA_MM = Object.freeze({ T: 15, F: 15, Ti: 15, A: 18, BAW: 20, Cd: 20 });

/** In a true side profile the far-side landmark is always occluded (that's
 * how rotation is detected), so side-pose segments are judged on the
 * better-seen landmark of each L/R pair. */
function nearSide(worldLandmarks, leftIndex, rightIndex) {
  const left = worldLandmarks[leftIndex], right = worldLandmarks[rightIndex];
  return left.visibility >= right.visibility ? left : right;
}

/** This scan's σ per segment, in the wire shape of models.py's
 * ScanSigmaOverrides — sent with the profile so the engine's confidence
 * reflects how well *this* scan saw the body, not a fixed guess.
 *
 * T is derived (shoulder height above seat / K_SH — see
 * computeSittingHeightMm), so its σ is the shoulder-height measurement's σ
 * divided by K_SH: that way k_sh·σ_T, the seat-height σ the engine
 * computes, equals the σ of what was actually measured. Bilateral segments
 * report the worse of the two sides. */
export function computeScanSigmaMm(frontWorld, seatedWorld, sideStandingWorld) {
  const L = POSE_LANDMARK;
  const sigma = (base, landmarks) => segmentConfidenceSigmaMm(base, landmarks);
  const worseSide = (base, leftIdx, rightIdx) =>
    Math.max(sigma(base, leftIdx.map((i) => frontWorld[i])), sigma(base, rightIdx.map((i) => frontWorld[i])));
  return {
    sigma_T_mm:
      sigma(BASE_SIGMA_MM.T, [
        nearSide(seatedWorld, L.LEFT_SHOULDER, L.RIGHT_SHOULDER),
        nearSide(seatedWorld, L.LEFT_HIP, L.RIGHT_HIP),
      ]) / K_SH,
    sigma_F_mm: worseSide(BASE_SIGMA_MM.F, [L.LEFT_HIP, L.LEFT_KNEE], [L.RIGHT_HIP, L.RIGHT_KNEE]),
    sigma_Ti_mm: worseSide(BASE_SIGMA_MM.Ti, [L.LEFT_KNEE, L.LEFT_ANKLE], [L.RIGHT_KNEE, L.RIGHT_ANKLE]),
    sigma_A_mm: worseSide(
      BASE_SIGMA_MM.A,
      [L.LEFT_SHOULDER, L.LEFT_ELBOW, L.LEFT_WRIST],
      [L.RIGHT_SHOULDER, L.RIGHT_ELBOW, L.RIGHT_WRIST],
    ),
    sigma_BAW_mm: sigma(BASE_SIGMA_MM.BAW, [frontWorld[L.LEFT_SHOULDER], frontWorld[L.RIGHT_SHOULDER]]),
    sigma_Cd_mm:
      sigma(BASE_SIGMA_MM.Cd, [
        nearSide(sideStandingWorld, L.LEFT_SHOULDER, L.RIGHT_SHOULDER),
        nearSide(sideStandingWorld, L.LEFT_HIP, L.RIGHT_HIP),
      ]) * CD_CONFIDENCE_PENALTY_MULTIPLIER,
  };
}

// ---------------------------------------------------------------------------
// Smoke test — mirrors this project's Python `if __name__ == "__main__":`
// convention. Synthetic landmark data with hand-verifiable geometry (mostly
// 3-4-5-triangle style deltas), no real MediaPipe/camera/browser needed.
// Run: node scan/measurements.mjs
//
// Node-only: this whole block (including the `node:url` import used for the
// __main__-style guard) must never execute in a browser — a static
// top-level `import "node:url"` broke test_harness.html entirely on first
// real-device testing (browsers can't resolve the `node:` scheme, which
// aborts the whole module's evaluation, so nothing on the page worked at
// all). Guarded by a Node-runtime check first; the `node:url` import itself
// is dynamic and only reached when that check passes, so browsers never
// attempt to load it.
// ---------------------------------------------------------------------------

function approxEqual(actual, expected, epsilon, label) {
  if (Math.abs(actual - expected) > epsilon) {
    throw new Error(`${label}: expected ${expected}, got ${actual}`);
  }
}

function landmark(x, y, z, visibility = 1.0) {
  return { x, y, z, visibility };
}

// z values below are deliberately large/mismatched (wildly different
// between paired landmarks) precisely to prove z is ignored — if the
// distance functions ever accidentally reincorporated z, these tests would
// fail loudly instead of silently passing on coincidentally-small z noise.

function buildFrontLandmarks() {
  const L = POSE_LANDMARK;
  const arr = new Array(33).fill(null).map(() => landmark(0, 0, 0));

  // Left leg: hip -> knee via (0.3,-0.4) => 500mm; knee -> ankle via
  // (0,-0.6) => 600mm.
  arr[L.LEFT_HIP] = landmark(0, 0, 50);
  arr[L.LEFT_KNEE] = landmark(0.3, -0.4, -80);
  arr[L.LEFT_ANKLE] = landmark(0.3, -1.0, 200);

  // Right leg: hip(0.3,0) -> knee via (0.6,-0.8) => 1000mm; knee -> ankle
  // via (0,-0.9) => 900mm.
  arr[L.RIGHT_HIP] = landmark(0.3, 0, -999);
  arr[L.RIGHT_KNEE] = landmark(0.9, -0.8, 999);
  arr[L.RIGHT_ANKLE] = landmark(0.9, -1.7, 0);

  // Shoulders 300mm apart (also doubles as BAW).
  arr[L.LEFT_SHOULDER] = landmark(0, 1.4, 15);
  arr[L.RIGHT_SHOULDER] = landmark(0.3, 1.4, -15);

  // Left arm: shoulder -> elbow via (0.24,-0.32) => 400mm; elbow -> wrist
  // via (0,-0.3) => 300mm. Total arm_L = 700mm.
  arr[L.LEFT_ELBOW] = landmark(0.24, 1.08, 7);
  arr[L.LEFT_WRIST] = landmark(0.24, 0.78, -7);

  // Right arm: shoulder -> elbow via (0.48,-0.64) => 800mm; elbow -> wrist
  // via (0,-0.9) => 900mm. Total arm_R = 1700mm.
  arr[L.RIGHT_ELBOW] = landmark(0.78, 0.76, 3);
  arr[L.RIGHT_WRIST] = landmark(0.78, -0.14, -3);

  // Ear/ankle for the model's own height estimate: earMid(3.6,2.65) ->
  // ankleMid(0.6,-1.35) => 5000mm (3-4-5 triangle x1000: dx=3.0,dy=4.0).
  // ankleMid here is exactly the midpoint of the two ankles set above.
  arr[L.LEFT_EAR] = landmark(3.45, 2.65, -40);
  arr[L.RIGHT_EAR] = landmark(3.75, 2.65, 40);

  return arr;
}

function buildSeatedLandmarks() {
  const L = POSE_LANDMARK;
  const arr = new Array(33).fill(null).map(() => landmark(0, 0, 0));
  // shoulderMid(0.2,1.1) -> hipMid(0.2,0.6) => 500mm (pure vertical delta).
  // Ears placed well above the shoulders so a regression back to ear-hip
  // would fail the assertion instead of passing by coincidence.
  arr[L.LEFT_EAR] = landmark(0.1, 1.5, 500);
  arr[L.RIGHT_EAR] = landmark(0.3, 1.5, -500);
  arr[L.LEFT_SHOULDER] = landmark(0.1, 1.1, 300);
  arr[L.RIGHT_SHOULDER] = landmark(0.3, 1.1, -300);
  arr[L.LEFT_HIP] = landmark(0.1, 0.6, -600);
  arr[L.RIGHT_HIP] = landmark(0.3, 0.6, 600);
  return arr;
}

if (typeof process !== "undefined" && process.versions && process.versions.node) {
  const { fileURLToPath } = await import("node:url");
  if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const EPS = 1e-6;

  // --- Calibration factor ---
  const front = buildFrontLandmarks();
  approxEqual(estimateModelHeightMm(front), 5000, EPS, "estimateModelHeightMm");
  const calibrationFactor = computeCalibrationFactor(front, 1750);
  approxEqual(calibrationFactor, 0.3115, EPS, "computeCalibrationFactor (1750mm × 0.89 expected ear-ankle / 5000mm model)");

  try {
    computeCalibrationFactor(front, 0);
    throw new Error("computeCalibrationFactor should have thrown for userHeightMm <= 0");
  } catch (e) {
    if (!e.message.includes("positive number")) throw e;
  }
  try {
    const degenerate = buildFrontLandmarks();
    const L = POSE_LANDMARK;
    degenerate[L.LEFT_EAR] = degenerate[L.LEFT_ANKLE] = landmark(0, 0, 0);
    degenerate[L.RIGHT_EAR] = degenerate[L.RIGHT_ANKLE] = landmark(0, 0, 0);
    computeCalibrationFactor(degenerate, 1750);
    throw new Error("computeCalibrationFactor should have thrown for degenerate (zero) model height");
  } catch (e) {
    if (!e.message.includes("degenerate landmarks")) throw e;
  }
  console.log("calibration factor: OK");

  // --- Front measurements, factor = 1 (raw geometry check) ---
  const rawFront = computeFrontMeasurementsMm(front, 1.0);
  approxEqual(rawFront.femur_L_mm, 500, EPS, "femur_L_mm (factor=1)");
  approxEqual(rawFront.femur_R_mm, 1000, EPS, "femur_R_mm (factor=1)");
  approxEqual(rawFront.tibia_L_mm, 600, EPS, "tibia_L_mm (factor=1)");
  approxEqual(rawFront.tibia_R_mm, 900, EPS, "tibia_R_mm (factor=1)");
  approxEqual(rawFront.arm_L_mm, 700, EPS, "arm_L_mm (factor=1)");
  approxEqual(rawFront.arm_R_mm, 1700, EPS, "arm_R_mm (factor=1)");
  approxEqual(rawFront.biacromial_width_mm, 300, EPS, "biacromial_width_mm (factor=1)");
  console.log("front measurements (factor=1): OK");

  // --- Front measurements, real calibration factor applied (scaling check) ---
  const calibratedFront = computeFrontMeasurementsMm(front, calibrationFactor);
  for (const key of Object.keys(rawFront)) {
    approxEqual(calibratedFront[key], rawFront[key] * calibrationFactor, 1e-9, `${key} (calibrated)`);
  }
  console.log("front measurements (calibrated scaling): OK");

  // --- Seated capture -> T ---
  const seated = buildSeatedLandmarks();
  approxEqual(computeShoulderHeightAboveSeatMm(seated, 1.0), 590, EPS, "shoulder above seat (500 + 90, factor=1)");
  approxEqual(computeShoulderHeightAboveSeatMm(seated, 2.0), 1090, EPS, "shoulder above seat (1000 + 90, factor=2)");
  approxEqual(computeSittingHeightMm(seated, 1.0), 590 / K_SH, EPS, "computeSittingHeightMm (factor=1)");
  // Round-trip contract with the engine: k_sh·T must give back the measured shoulder height.
  approxEqual(K_SH * computeSittingHeightMm(seated, 2.0), 1090, EPS, "k_sh·T round-trip (factor=2)");
  console.log("sitting height: OK");

  // --- Mask row width ---
  const maskWidth = 100;
  const maskHeight = 100;
  const mask = new Float32Array(maskWidth * maskHeight); // all zero (background)
  for (let x = 20; x <= 59; x++) mask[30 * maskWidth + x] = 1.0; // row 30: foreground 20..59
  approxEqual(measureMaskRowWidthPx(mask, maskWidth, maskHeight, 30), 40, EPS, "measureMaskRowWidthPx (row 30)");
  if (measureMaskRowWidthPx(mask, maskWidth, maskHeight, 0) !== null) {
    throw new Error("measureMaskRowWidthPx (empty row) should return null");
  }
  console.log("mask row width: OK");

  // --- Chest depth (Cd) via segmentation mask ---
  const L = POSE_LANDMARK;
  const cdWorld = new Array(33).fill(null).map(() => landmark(0, 0, 0));
  cdWorld[L.LEFT_SHOULDER] = cdWorld[L.RIGHT_SHOULDER] = landmark(0, 0.25, 0);
  cdWorld[L.LEFT_HIP] = cdWorld[L.RIGHT_HIP] = landmark(0, -0.25, 0); // shoulder-hip = 0.5m
  const cdNormalized = new Array(33).fill(null).map(() => ({ x: 0, y: 0 }));
  cdNormalized[L.LEFT_SHOULDER] = cdNormalized[L.RIGHT_SHOULDER] = { x: 0.5, y: 0.3 };
  cdNormalized[L.LEFT_HIP] = cdNormalized[L.RIGHT_HIP] = { x: 0.5, y: 0.8 }; // pixel dy = 50px -> 0.01 m/px

  const cdMm = computeChestDepthMm(
    {
      worldLandmarks: cdWorld,
      normalizedLandmarks: cdNormalized,
      maskFloat32Array: mask, // row 30 = shoulder row (0.3 * 100), width 40px -> 400mm model meters
      maskWidth,
      maskHeight,
    },
    2.0,
  );
  approxEqual(cdMm, 800, EPS, "computeChestDepthMm (40px * 10mm/px * factor=2)");
  console.log("chest depth (Cd): OK");

  // --- Dynamic confidence sigma ---
  approxEqual(segmentConfidenceSigmaMm(15, [landmark(0, 0, 0, 1.0), landmark(0, 0, 0, 0.95)]), 15, EPS, "sigma (high visibility)");
  approxEqual(segmentConfidenceSigmaMm(15, [landmark(0, 0, 0, 0.9)]), 15, EPS, "sigma (exactly at floor)");
  approxEqual(segmentConfidenceSigmaMm(15, [landmark(0, 0, 0, 0.4), landmark(0, 0, 0, 0.9)]), 45, EPS, "sigma (min visibility 0.4)");
  approxEqual(segmentConfidenceSigmaMm(15, [landmark(0, 0, 0, 0)]), 15 * 4.6, EPS, "sigma (visibility 0)");
  approxEqual(segmentConfidenceSigmaMm(15, [landmark(0, 0, 0, -0.2)]), 15 * 4.6, EPS, "sigma (clamped negative visibility)");
  approxEqual(CD_CONFIDENCE_PENALTY_MULTIPLIER, 1.5, EPS, "CD_CONFIDENCE_PENALTY_MULTIPLIER");
  console.log("dynamic confidence sigma: OK");

  // --- Per-scan sigma bundle ---
  const allVisible = buildFrontLandmarks();
  const seatedForSigma = buildSeatedLandmarks();
  // Side pose: far-side shoulder/hip occluded (visibility 0) — must not inflate T/Cd.
  seatedForSigma[L.RIGHT_SHOULDER] = landmark(0.3, 1.1, 0, 0.0);
  seatedForSigma[L.RIGHT_HIP] = landmark(0.3, 0.6, 0, 0.0);
  const clean = computeScanSigmaMm(allVisible, seatedForSigma, seatedForSigma);
  approxEqual(clean.sigma_T_mm, 15 / K_SH, EPS, "sigma_T (derived, near side clear)");
  approxEqual(K_SH * clean.sigma_T_mm, 15, EPS, "k_sh·σ_T = shoulder-height σ");
  approxEqual(clean.sigma_F_mm, 15, EPS, "sigma_F (both sides clear)");
  approxEqual(clean.sigma_Cd_mm, 30, EPS, "sigma_Cd (base 20 × 1.5 penalty)");
  const blurryKnee = buildFrontLandmarks();
  blurryKnee[L.RIGHT_KNEE] = landmark(0.9, -0.8, 0, 0.4);
  approxEqual(computeScanSigmaMm(blurryKnee, seatedForSigma, seatedForSigma).sigma_F_mm, 45, EPS, "sigma_F (worse side governs)");
  console.log("per-scan sigma bundle: OK");

  console.log("\nAll scan/measurements.mjs smoke tests passed.");
  }
}
