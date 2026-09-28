// Zone 2: live capture quality gating — pure logic over already-detected
// MediaPipe landmark data (normalized 2D + world 3D), no camera/DOM/canvas
// access here. Real pixel sampling (brightness) and the actual video loop
// belong to Zone 3; this module only decides pass/fail given numbers it's
// handed. Implements the priority-ordered check list decided in
// PRODUCT_ROADMAP_NOTES.md's "Live quality gating during capture" section.
//
// Thresholds below are explicit, named, and deliberately simple v1 values —
// not fixed by any spec, same discipline as this project's illustrative
// FrameConstants placeholders elsewhere. Expect to tune against real device
// testing.

import { POSE_LANDMARK } from "./measurements.mjs";

export const POSE_KIND = Object.freeze({
  FRONT: "front",
  SIDE_STANDING: "side_standing",
  SIDE_SEATED: "side_seated",
});

// ---------------------------------------------------------------------------
// 1. Framing / cropping — normalized 2D landmarks only.
// ---------------------------------------------------------------------------

const EDGE_MARGIN = 0.03; // fraction of frame width/height treated as "off-screen"
const MIN_VERTICAL_EXTENT_FRACTION = 0.5; // standing poses: nose-to-heel should occupy at least half the frame height
// Seated: legs are bent forward at the knee, not a vertical extension of
// the torso the way standing legs are, so nose-to-heel isn't a meaningful
// "how much of the frame does the body fill" proxy here — a properly
// framed seated shot can have a much smaller nose-to-heel span than a
// standing one even at the same distance from camera. Use nose-to-hip
// (close to the segment this pose actually measures — sitting height T,
// see measurements.mjs's computeSittingHeightMm) as the frame-fill proxy
// instead. Tuned against a real confirmed-good seated capture (2026-07-08)
// that read 0.229 — this sits comfortably below that, so a normally-framed
// seated shot passes; a genuinely-too-far one reads far smaller still.
const MIN_SEATED_VERTICAL_EXTENT_FRACTION = 0.18;

// REVISED 2026-07-08: dropped the low-visibility sub-condition. It conflated
// two different things — a limb actually cropped off-camera (real "step
// back" case) vs. a limb occluded by the person's own body (normal and
// expected in a side profile — the far wrist/heel is never visible there).
// A real device test showed "step back" firing even with the whole body
// correctly framed, purely because the far-side wrist/heel had low
// visibility from self-occlusion. Position near the frame edge is the
// actual signal for true cropping (an off-camera landmark's projected x/y
// sits at/near the boundary); visibility alone doesn't distinguish
// "off-camera" from "behind my own torso".
//
// REVISED again 2026-07-08 (same day, seated side-profile test): even the
// position check alone still misfired the same way. Sitting side-on (e.g.
// on a chair with a backrest), the far wrist/heel is genuinely occluded by
// the torso/chair, and MediaPipe's extrapolated guess for its position
// sometimes drifts near the frame edge even though nothing is actually
// cropped — same underlying problem (guessing instead of reporting real
// uncertainty), just showing up as position noise instead of visibility
// noise this time. Fixed by treating each L/R pair (wrist, heel) as
// cropped only if BOTH sides read near-edge simultaneously — a real crop
// event pushes both plausible guesses toward the boundary; one side's bad
// extrapolation alone shouldn't. The nose has no such pair to fall back on
// and is still checked directly (it's reliably tracked in every pose kind
// this project uses, including side profile).
function isNearFrameEdge(landmark) {
  return (
    landmark.x < EDGE_MARGIN ||
    landmark.x > 1 - EDGE_MARGIN ||
    landmark.y < EDGE_MARGIN ||
    landmark.y > 1 - EDGE_MARGIN
  );
}

/** Returns 'too_close' (something is cropped/off-frame — step back),
 * 'too_far' (body occupies too little of the frame — move closer), or null
 * (framing OK). `landmarks` are normalized image-space [0,1] landmarks.
 * `poseKind` picks the right "fills the frame" proxy — see
 * MIN_SEATED_VERTICAL_EXTENT_FRACTION's comment for why seated needs a
 * different one than standing. */
export function estimateFramingIssue(landmarks, poseKind) {
  const L = POSE_LANDMARK;
  const noseCropped = isNearFrameEdge(landmarks[L.NOSE]);
  const wristsCropped = isNearFrameEdge(landmarks[L.LEFT_WRIST]) && isNearFrameEdge(landmarks[L.RIGHT_WRIST]);
  const heelsCropped = isNearFrameEdge(landmarks[L.LEFT_HEEL]) && isNearFrameEdge(landmarks[L.RIGHT_HEEL]);
  if (noseCropped || wristsCropped || heelsCropped) return "too_close";

  if (poseKind === POSE_KIND.SIDE_SEATED) {
    // Nose, not ear-midpoint: in a true side profile the far ear is
    // completely hidden behind the skull (zero visual cue at all, worse
    // than the far shoulder/hip which at least has torso-width context),
    // so averaging left+right ear can pull the vertical position off in
    // a way that made this check misfire on a real seated capture. Nose
    // is already established elsewhere in this function as reliably
    // tracked in every pose kind, including side profile.
    const hipMidY = (landmarks[L.LEFT_HIP].y + landmarks[L.RIGHT_HIP].y) / 2;
    const seatedVerticalExtent = Math.abs(hipMidY - landmarks[L.NOSE].y);
    if (seatedVerticalExtent < MIN_SEATED_VERTICAL_EXTENT_FRACTION) return "too_far";
    return null;
  }

  const top = landmarks[L.NOSE].y;
  const bottom = Math.max(landmarks[L.LEFT_HEEL].y, landmarks[L.RIGHT_HEEL].y);
  const verticalExtent = bottom - top;
  if (verticalExtent < MIN_VERTICAL_EXTENT_FRACTION) return "too_far";

  return null;
}

// ---------------------------------------------------------------------------
// 2. Lighting — takes an already-computed average luminance (0..1), the
// actual pixel sampling is Zone 3's job (canvas/ImageData is browser-only).
// ---------------------------------------------------------------------------

const MIN_AVERAGE_LUMINANCE = 0.25;

export function isLightingOk(averageLuminance01) {
  return averageLuminance01 >= MIN_AVERAGE_LUMINANCE;
}

// ---------------------------------------------------------------------------
// 3. Pose alignment (front shot only) — shoulders/hips should be level.
// Scale-invariant: tilt is measured as a fraction of torso height, not an
// absolute pixel amount, so it works regardless of how far the person is
// from the camera.
// ---------------------------------------------------------------------------

const MAX_TILT_RATIO = 0.08;

export function estimateAlignmentTiltRatio(landmarks) {
  const L = POSE_LANDMARK;
  const shoulderTilt = Math.abs(landmarks[L.LEFT_SHOULDER].y - landmarks[L.RIGHT_SHOULDER].y);
  const hipTilt = Math.abs(landmarks[L.LEFT_HIP].y - landmarks[L.RIGHT_HIP].y);
  const shoulderMidY = (landmarks[L.LEFT_SHOULDER].y + landmarks[L.RIGHT_SHOULDER].y) / 2;
  const hipMidY = (landmarks[L.LEFT_HIP].y + landmarks[L.RIGHT_HIP].y) / 2;
  const torsoHeight = Math.abs(shoulderMidY - hipMidY);
  if (torsoHeight <= 0) return Infinity; // degenerate — treat as maximally misaligned
  return Math.max(shoulderTilt, hipTilt) / torsoHeight;
}

export function isAlignmentOk(landmarks) {
  return estimateAlignmentTiltRatio(landmarks) <= MAX_TILT_RATIO;
}

// ---------------------------------------------------------------------------
// 4. Rotation / facing direction.
//
// REVISED 2026-07-08, second time, after real-device testing. First
// revision (see git history) used world-landmark depth (z) vs. lateral (x)
// shoulder separation for both directions — abandoned because the
// on-device model's z estimates proved too unreliable to trust at all
// (see measurements.mjs's docstring for the identical root cause on the
// measurement side). Second revision used a 2D-only lateral-shoulder-vs-
// torso-height ratio for BOTH frontal and side detection — this worked
// well for frontal (confirmed ~1.14 on a real device, comfortably clear of
// the threshold) but never worked reliably for side profile across three
// tuned thresholds (0.35 too strict, 0.5 too lenient — accepted a
// half-turn, 0.3 still never fired for a careful full turn).
//
// User correctly identified the actual problem: in a true ~90° side
// profile, one shoulder is **always** genuinely invisible to the camera —
// this is a physical certainty (you cannot see both shoulders from a true
// side angle), not a probabilistic thing to test for. That led to a third
// revision using the model's own `visibility` confidence instead of
// position — reasonable in theory, but a real device test disproved it:
// standing in a genuine full side turn measured visibility asymmetry of
// only 0.002 (essentially zero) even though one shoulder/hip was
// completely turned away. MediaPipe does not reliably lower `visibility`
// for occluded-by-own-body landmarks — it keeps confidently guessing a
// plausible position for them instead of reporting low confidence, so
// this signal never actually reflected true occlusion.
//
// The SAME real capture measured estimateFacingRotationRatio at 0.044 —
// a huge, clean gap from the confirmed frontal reading of ~1.14. So the
// original 2D lateral-ratio signal was correct all along; the earlier
// "three tuned thresholds, never fires" failures were very likely caused
// by *other* gates blocking before rotation was ever evaluated (framing's
// old low-visibility cropped-check misfiring on normal self-occlusion —
// see estimateFramingIssue's comment — and, before an earlier fix, the
// occlusion check requiring both sides visible). Reverted to the ratio
// signal for side poses, just with the opposite direction: side profile
// needs a LOW ratio (shoulders collapse to nearly the same x), not a high
// one. `estimateProfileVisibilityAsymmetry` is kept only as a live
// diagnostic in test_harness.html, no longer used as a gate.
// ---------------------------------------------------------------------------

// REVISED 2026-09-28: was 0.5, which real numbers from a live scan showed
// was far too lenient. A real frontal capture confirmed ~1.14 (see below);
// 0.5 corresponds to cos(theta) = 0.5/1.14 ≈ 0.44, i.e. it let a capture
// through at roughly 64° off frontal. A user's own front-standing capture
// (2026-09-28) read a real shoulder width 22% short of a tape measurement,
// consistent with roughly 39° of rotation — this gate should have caught
// it and didn't. 1.1 tolerates about 15° off frontal (cos(15°) ≈ 0.966,
// 1.1/1.14 ≈ 0.965) before failing, which should still feel natural to
// hold but catches anything that would meaningfully shrink shoulder/arm
// width. Needs a real on-device check before the next demo: if this now
// rejects an honestly-frontal capture too often, loosen it back down.
const MIN_FRONTAL_LATERAL_RATIO = 1.1; // must be at least this wide (relative to torso height) to count as "facing camera" — confirmed ~1.14 on a real frontal capture, comfortably clear
const MAX_SIDE_LATERAL_RATIO = 0.3; // must be at most this narrow to count as true side profile — confirmed ~0.044 on a real side-profile capture (2026-07-08), comfortably below; a ~45° half-turn would sit closer to ~0.8, comfortably above

export function estimateFacingRotationRatio(landmarks) {
  const L = POSE_LANDMARK;
  const lateralGap = Math.abs(landmarks[L.LEFT_SHOULDER].x - landmarks[L.RIGHT_SHOULDER].x);
  const shoulderMidY = (landmarks[L.LEFT_SHOULDER].y + landmarks[L.RIGHT_SHOULDER].y) / 2;
  const hipMidY = (landmarks[L.LEFT_HIP].y + landmarks[L.RIGHT_HIP].y) / 2;
  const torsoHeight = Math.abs(shoulderMidY - hipMidY);
  if (torsoHeight <= 0) return 0;
  return lateralGap / torsoHeight;
}

export function isRotationOk(landmarks, poseKind) {
  const ratio = estimateFacingRotationRatio(landmarks);
  if (poseKind === POSE_KIND.FRONT) {
    return ratio >= MIN_FRONTAL_LATERAL_RATIO;
  }
  return ratio <= MAX_SIDE_LATERAL_RATIO; // side_standing / side_seated
}

/** The model's own confidence asymmetry between left/right shoulder+hip —
 * kept as a diagnostic only (see the section docstring above: this proved
 * unreliable as a gating signal, measuring ~0 on a genuine full side turn). */
export function estimateProfileVisibilityAsymmetry(landmarks) {
  const L = POSE_LANDMARK;
  const leftSideVisibility = (landmarks[L.LEFT_SHOULDER].visibility + landmarks[L.LEFT_HIP].visibility) / 2;
  const rightSideVisibility = (landmarks[L.RIGHT_SHOULDER].visibility + landmarks[L.RIGHT_HIP].visibility) / 2;
  return Math.abs(leftSideVisibility - rightSideVisibility);
}

// ---------------------------------------------------------------------------
// 5. Joint occlusion — a specific joint persistently low-visibility despite
// framing/lighting/rotation already passing (checked in that order, so by
// the time this runs we know the problem is localized, not global).
// ---------------------------------------------------------------------------

const MIN_JOINT_VISIBILITY = 0.5;

// Paired L/R landmark indices -> one friendly name for the on-screen message.
const OCCLUSION_CHECK_GROUPS_BY_POSE = {
  [POSE_KIND.FRONT]: [
    { name: "hip", indices: [POSE_LANDMARK.LEFT_HIP, POSE_LANDMARK.RIGHT_HIP] },
    { name: "knee", indices: [POSE_LANDMARK.LEFT_KNEE, POSE_LANDMARK.RIGHT_KNEE] },
    { name: "ankle", indices: [POSE_LANDMARK.LEFT_ANKLE, POSE_LANDMARK.RIGHT_ANKLE] },
    { name: "shoulder", indices: [POSE_LANDMARK.LEFT_SHOULDER, POSE_LANDMARK.RIGHT_SHOULDER] },
    { name: "elbow", indices: [POSE_LANDMARK.LEFT_ELBOW, POSE_LANDMARK.RIGHT_ELBOW] },
    { name: "wrist", indices: [POSE_LANDMARK.LEFT_WRIST, POSE_LANDMARK.RIGHT_WRIST] },
  ],
  // SIDE_STANDING / SIDE_SEATED intentionally have no bilateral occlusion
  // checks: in a true profile, one entire side (shoulder, hip, ear — every
  // bilateral pair) is *always* genuinely occluded by the body itself
  // (see isRotationOk's docstring — that's the exact signal rotation
  // detection now relies on). A "both sides must be visible" check would
  // directly contradict that and make side poses permanently unable to
  // reach "ready". No equivalent-but-safe replacement check for
  // clothing-occlusion specifically on the near side is implemented yet —
  // out of scope for now, the rotation check is the load-bearing gate here.
  [POSE_KIND.SIDE_STANDING]: [],
  [POSE_KIND.SIDE_SEATED]: [],
};

/** Returns the friendly name of the first group with low visibility on
 * either side, or null if every checked joint is visible enough. */
export function findOccludedJoint(landmarks, poseKind) {
  const groups = OCCLUSION_CHECK_GROUPS_BY_POSE[poseKind] || [];
  for (const group of groups) {
    const lowVisibility = group.indices.some((i) => landmarks[i].visibility < MIN_JOINT_VISIBILITY);
    if (lowVisibility) return group.name;
  }
  return null;
}

// ---------------------------------------------------------------------------
// 6. Jitter / stability — needs a short window of recent frames. Also
// reused for the decided "average landmarks over the stable window" frame-
// averaging step (same window, no separate pass needed).
// ---------------------------------------------------------------------------

const MAX_JITTER_RATIO = 0.02; // as a fraction of torso height, same scale-invariance trick as tilt

/** Mean frame-to-frame movement of the hip-center across a window of
 * consecutive normalized-landmark frames, scaled by torso height so it
 * doesn't depend on distance from camera. Needs at least 2 frames. */
export function computeLandmarkJitterRatio(recentFramesLandmarks) {
  const L = POSE_LANDMARK;
  if (recentFramesLandmarks.length < 2) return 0;

  const hipCenters = recentFramesLandmarks.map((landmarks) => ({
    x: (landmarks[L.LEFT_HIP].x + landmarks[L.RIGHT_HIP].x) / 2,
    y: (landmarks[L.LEFT_HIP].y + landmarks[L.RIGHT_HIP].y) / 2,
  }));
  let totalMovement = 0;
  for (let i = 1; i < hipCenters.length; i++) {
    const dx = hipCenters[i].x - hipCenters[i - 1].x;
    const dy = hipCenters[i].y - hipCenters[i - 1].y;
    totalMovement += Math.sqrt(dx * dx + dy * dy);
  }
  const meanMovement = totalMovement / (hipCenters.length - 1);

  const last = recentFramesLandmarks[recentFramesLandmarks.length - 1];
  const shoulderMidY = (last[L.LEFT_SHOULDER].y + last[L.RIGHT_SHOULDER].y) / 2;
  const hipMidY = (last[L.LEFT_HIP].y + last[L.RIGHT_HIP].y) / 2;
  const torsoHeight = Math.abs(shoulderMidY - hipMidY);
  if (torsoHeight <= 0) return Infinity;

  return meanMovement / torsoHeight;
}

export function isStable(recentFramesLandmarks) {
  return computeLandmarkJitterRatio(recentFramesLandmarks) <= MAX_JITTER_RATIO;
}

/** Averages every landmark's x/y/z/visibility across a stability window —
 * the decided "frame averaging" step, reducing per-frame noise essentially
 * for free since the user is already required to hold still for this long
 * anyway. Works on either normalized or world landmark arrays (same shape). */
export function averageLandmarksOverWindow(recentFramesLandmarks) {
  const frameCount = recentFramesLandmarks.length;
  const landmarkCount = recentFramesLandmarks[0].length;
  const averaged = new Array(landmarkCount);
  for (let i = 0; i < landmarkCount; i++) {
    let x = 0, y = 0, z = 0, visibility = 0;
    for (const frame of recentFramesLandmarks) {
      x += frame[i].x;
      y += frame[i].y;
      z += frame[i].z;
      visibility += frame[i].visibility;
    }
    averaged[i] = { x: x / frameCount, y: y / frameCount, z: z / frameCount, visibility: visibility / frameCount };
  }
  return averaged;
}

// ---------------------------------------------------------------------------
// Orchestration — priority-ordered single-message gate, per
// PRODUCT_ROADMAP_NOTES.md. Returns the first failing check only; callers
// (Zone 4's state machine) show one message at a time, never stack them.
// ---------------------------------------------------------------------------

export const QUALITY_MESSAGE = Object.freeze({
  too_close: "Step back a little",
  too_far: "Move a bit closer",
  too_dark: "Too little light",
  misaligned: "Stand up straight, facing the camera",
  wrong_rotation_front: "Turn to face the camera",
  wrong_rotation_side: "Turn to a strict side-on position",
  jittery: "Hold still for a moment",
});

function occludedJointMessage(jointName) {
  return `Can't see your ${jointName} clearly. Your clothes might be too loose there`;
}

/**
 * @param input.landmarks - normalized 2D landmarks for the current frame (all checks in this
 *   module are 2D-only — see estimateFacingRotationRatio's docstring for why world/z landmarks
 *   were dropped after real-device testing)
 * @param input.averageLuminance01 - precomputed frame brightness, 0..1 (Zone 3's job to sample)
 * @param input.poseKind - one of POSE_KIND
 * @param input.recentFramesLandmarks - normalized-landmark history including the current frame, oldest first
 * @returns {{ ready: boolean, code: string|null, message: string|null }}
 */
export function evaluateCaptureQuality(input) {
  const { landmarks, averageLuminance01, poseKind, recentFramesLandmarks } = input;

  const framingIssue = estimateFramingIssue(landmarks, poseKind);
  if (framingIssue) return { ready: false, code: framingIssue, message: QUALITY_MESSAGE[framingIssue] };

  if (!isLightingOk(averageLuminance01)) {
    return { ready: false, code: "too_dark", message: QUALITY_MESSAGE.too_dark };
  }

  if (poseKind === POSE_KIND.FRONT && !isAlignmentOk(landmarks)) {
    return { ready: false, code: "misaligned", message: QUALITY_MESSAGE.misaligned };
  }

  if (!isRotationOk(landmarks, poseKind)) {
    const code = poseKind === POSE_KIND.FRONT ? "wrong_rotation_front" : "wrong_rotation_side";
    return { ready: false, code, message: QUALITY_MESSAGE[code] };
  }

  const occludedJoint = findOccludedJoint(landmarks, poseKind);
  if (occludedJoint) {
    return { ready: false, code: "occluded_joint", message: occludedJointMessage(occludedJoint) };
  }

  if (recentFramesLandmarks && recentFramesLandmarks.length >= 2 && !isStable(recentFramesLandmarks)) {
    return { ready: false, code: "jittery", message: QUALITY_MESSAGE.jittery };
  }

  return { ready: true, code: null, message: null };
}

// ---------------------------------------------------------------------------
// Smoke test — same convention as scan/measurements.mjs. Node-only guard:
// see measurements.mjs's comment on why the `node:url` import must be
// dynamic and gated behind a runtime check, never a static top-level
// import (it broke test_harness.html entirely on first real-device test).
// Run: node scan/quality_gates.mjs
// ---------------------------------------------------------------------------

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function lm(x, y, z, visibility = 1.0) {
  return { x, y, z, visibility };
}

function buildGoodFrontLandmarks() {
  const L = POSE_LANDMARK;
  const arr = new Array(33).fill(null).map(() => lm(0.5, 0.5, 0));
  arr[L.NOSE] = lm(0.5, 0.1, 0);
  // Shoulder gap 0.34, torso height 0.30 -> ratio 1.133, matching the real
  // ~1.14 reference a genuine frontal capture reads (see
  // MIN_FRONTAL_LATERAL_RATIO's comment) rather than an arbitrary number.
  arr[L.LEFT_SHOULDER] = lm(0.33, 0.25, 0);
  arr[L.RIGHT_SHOULDER] = lm(0.67, 0.25, 0);
  arr[L.LEFT_ELBOW] = lm(0.31, 0.4, 0);
  arr[L.RIGHT_ELBOW] = lm(0.69, 0.4, 0);
  arr[L.LEFT_WRIST] = lm(0.29, 0.55, 0);
  arr[L.RIGHT_WRIST] = lm(0.71, 0.55, 0);
  arr[L.LEFT_HIP] = lm(0.45, 0.55, 0);
  arr[L.RIGHT_HIP] = lm(0.55, 0.55, 0);
  arr[L.LEFT_KNEE] = lm(0.44, 0.75, 0);
  arr[L.RIGHT_KNEE] = lm(0.56, 0.75, 0);
  arr[L.LEFT_ANKLE] = lm(0.44, 0.9, 0);
  arr[L.RIGHT_ANKLE] = lm(0.56, 0.9, 0);
  arr[L.LEFT_HEEL] = lm(0.44, 0.92, 0);
  arr[L.RIGHT_HEEL] = lm(0.56, 0.92, 0);
  return arr;
}

// Side-profile fixture: right shoulder/hip given low visibility (the
// far/occluded side in a true profile — the load-bearing part of this
// fixture now that rotation detection uses visibility asymmetry, not
// position) — otherwise identical to buildGoodFrontLandmarks so
// framing/occlusion checks still pass on it.
function buildProfileLandmarks() {
  const arr = buildGoodFrontLandmarks();
  const L = POSE_LANDMARK;
  arr[L.LEFT_SHOULDER] = lm(0.5, 0.25, 0, 0.9);
  arr[L.RIGHT_SHOULDER] = lm(0.51, 0.25, 0, 0.2);
  arr[L.LEFT_HIP] = lm(0.5, 0.55, 0, 0.9);
  arr[L.RIGHT_HIP] = lm(0.51, 0.55, 0, 0.2);
  return arr;
}

if (typeof process !== "undefined" && process.versions && process.versions.node) {
  const { fileURLToPath } = await import("node:url");
  if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const L = POSE_LANDMARK;

  // --- Framing ---
  const good = buildGoodFrontLandmarks();
  assertEqual(estimateFramingIssue(good, POSE_KIND.FRONT), null, "framing (good)");

  const cropped = buildGoodFrontLandmarks();
  cropped[L.LEFT_WRIST] = lm(0.01, 0.55, 0);
  cropped[L.RIGHT_WRIST] = lm(0.01, 0.55, 0); // both pinned to the edge
  assertEqual(estimateFramingIssue(cropped, POSE_KIND.FRONT), "too_close", "framing (both wrists cropped)");

  // A single occluded side reading a bogus near-edge guess (e.g. the far
  // wrist in a seated side profile) must NOT trip framing on its own —
  // the real 2026-07-08 bug this fixture guards against.
  const oneSideBogus = buildGoodFrontLandmarks();
  oneSideBogus[L.LEFT_WRIST] = lm(0.01, 0.55, 0); // only one side near edge
  assertEqual(estimateFramingIssue(oneSideBogus, POSE_KIND.FRONT), null, "framing (one occluded wrist near edge, not cropped)");

  const noseCropped = buildGoodFrontLandmarks();
  noseCropped[L.NOSE] = lm(0.5, 0.01, 0); // nose has no pair to fall back on
  assertEqual(estimateFramingIssue(noseCropped, POSE_KIND.FRONT), "too_close", "framing (nose cropped)");

  const tooFar = buildGoodFrontLandmarks();
  tooFar[L.NOSE] = lm(0.5, 0.45, 0);
  tooFar[L.LEFT_HEEL] = lm(0.44, 0.55, 0);
  tooFar[L.RIGHT_HEEL] = lm(0.56, 0.55, 0); // vertical extent now only 0.1
  assertEqual(estimateFramingIssue(tooFar, POSE_KIND.FRONT), "too_far", "framing (too far, standing)");

  // Seated: legs bent forward means nose-to-heel isn't the right proxy —
  // nose-to-hip is what actually matters here (see MIN_SEATED_VERTICAL_
  // EXTENT_FRACTION's comment). Hips sit at y=0.55, nose at y=0.1 in this
  // base fixture -> extent 0.45, above the 0.25 floor.
  assertEqual(estimateFramingIssue(good, POSE_KIND.SIDE_SEATED), null, "framing (seated, good nose-hip extent)");

  const seatedTooFar = buildGoodFrontLandmarks();
  seatedTooFar[L.NOSE] = lm(0.5, 0.4, 0); // nose-hip extent now only 0.15
  assertEqual(estimateFramingIssue(seatedTooFar, POSE_KIND.SIDE_SEATED), "too_far", "framing (seated, too far)");
  console.log("framing: OK");

  // --- Lighting ---
  assertEqual(isLightingOk(0.5), true, "lighting (bright)");
  assertEqual(isLightingOk(0.1), false, "lighting (dark)");
  console.log("lighting: OK");

  // --- Alignment ---
  assertEqual(isAlignmentOk(good), true, "alignment (level)");
  const tilted = buildGoodFrontLandmarks();
  tilted[L.RIGHT_SHOULDER] = lm(0.6, 0.29, 0); // shoulders now 0.04 apart in y, torso ~0.3 -> ratio ~0.13
  assertEqual(isAlignmentOk(tilted), false, "alignment (tilted)");
  console.log("alignment: OK");

  // --- Rotation ---
  const profile = buildProfileLandmarks();
  assertEqual(isRotationOk(good, POSE_KIND.FRONT), true, "rotation (frontal, expect front)");
  assertEqual(isRotationOk(good, POSE_KIND.SIDE_STANDING), false, "rotation (frontal, expect side)");
  assertEqual(isRotationOk(profile, POSE_KIND.SIDE_STANDING), true, "rotation (profile, expect side)");
  assertEqual(isRotationOk(profile, POSE_KIND.FRONT), false, "rotation (profile, expect front)");

  // A real regression: a torso rotated ~30° off frontal used to pass the old
  // 0.5 threshold (ratio here is ~0.98) and produced a shoulder width ~14%
  // short. It must fail now.
  const rotated30deg = buildGoodFrontLandmarks();
  const cos30 = Math.cos((30 * Math.PI) / 180);
  const shoulderMidX = (rotated30deg[L.LEFT_SHOULDER].x + rotated30deg[L.RIGHT_SHOULDER].x) / 2;
  const halfGap = ((rotated30deg[L.RIGHT_SHOULDER].x - rotated30deg[L.LEFT_SHOULDER].x) / 2) * cos30;
  rotated30deg[L.LEFT_SHOULDER] = lm(shoulderMidX - halfGap, 0.25, 0);
  rotated30deg[L.RIGHT_SHOULDER] = lm(shoulderMidX + halfGap, 0.25, 0);
  const rotatedRatio = estimateFacingRotationRatio(rotated30deg);
  assertEqual(rotatedRatio > 0.5 && rotatedRatio < 1.1, true, `rotation (30deg fixture sanity, got ${rotatedRatio})`);
  assertEqual(isRotationOk(rotated30deg, POSE_KIND.FRONT), false, "rotation (30deg off frontal, expect rejected)");
  console.log("rotation: OK");

  // --- Occlusion ---
  assertEqual(findOccludedJoint(good, POSE_KIND.FRONT), null, "occlusion (none)");
  const occluded = buildGoodFrontLandmarks();
  occluded[L.LEFT_KNEE] = lm(0.44, 0.75, 0, 0.2);
  assertEqual(findOccludedJoint(occluded, POSE_KIND.FRONT), "knee", "occlusion (knee)");
  console.log("occlusion: OK");

  // --- Jitter + averaging ---
  const stableFrames = [buildGoodFrontLandmarks(), buildGoodFrontLandmarks()];
  assertEqual(isStable(stableFrames), true, "jitter (stable)");

  const movedFrame = buildGoodFrontLandmarks();
  movedFrame[L.LEFT_HIP] = lm(0.45 + 0.05, 0.55, 0);
  movedFrame[L.RIGHT_HIP] = lm(0.55 + 0.05, 0.55, 0);
  const jitteryFrames = [buildGoodFrontLandmarks(), movedFrame];
  assertEqual(isStable(jitteryFrames), false, "jitter (moved)");
  console.log("jitter: OK");

  const tinyFrame1 = [lm(0, 0, 0, 1), lm(10, 10, 10, 1)];
  const tinyFrame2 = [lm(2, 4, 6, 0), lm(10, 10, 10, 1)];
  const averaged = averageLandmarksOverWindow([tinyFrame1, tinyFrame2]);
  assertEqual(averaged[0].x, 1, "averaging (x)");
  assertEqual(averaged[0].y, 2, "averaging (y)");
  assertEqual(averaged[0].z, 3, "averaging (z)");
  assertEqual(averaged[0].visibility, 0.5, "averaging (visibility)");
  console.log("frame averaging: OK");

  // --- Orchestration priority order ---
  const readyResult = evaluateCaptureQuality({
    landmarks: good,
    averageLuminance01: 0.6,
    poseKind: POSE_KIND.FRONT,
    recentFramesLandmarks: stableFrames,
  });
  assertEqual(readyResult.ready, true, "orchestration (all good)");

  // Both lighting AND alignment fail here — lighting must win (checked first).
  const priorityResult = evaluateCaptureQuality({
    landmarks: tilted,
    averageLuminance01: 0.05,
    poseKind: POSE_KIND.FRONT,
  });
  assertEqual(priorityResult.code, "too_dark", "orchestration (lighting beats alignment)");

  const sideStableFrames = [buildProfileLandmarks(), buildProfileLandmarks()];
  const sideReadyResult = evaluateCaptureQuality({
    landmarks: profile,
    averageLuminance01: 0.6,
    poseKind: POSE_KIND.SIDE_STANDING,
    recentFramesLandmarks: sideStableFrames,
  });
  assertEqual(sideReadyResult.ready, true, "orchestration (side profile ready)");
  console.log("orchestration: OK");

  console.log("\nAll scan/quality_gates.mjs smoke tests passed.");
  }
}
