// Zone 4: capture flow state machine — sequences the three poses
// (front -> side_standing -> side_seated), tracks progress, and owns the
// per-pose instructional copy. Pure logic, no camera/DOM here (same
// discipline as Zones 1-2): takes explicit events (capture fired, redo
// requested) and returns a new state, so it's trivially unit-testable and
// the harness/real UI just renders whatever this returns.
//
// Deliberately does NOT hold the actual measurement data (landmarks,
// worldLandmarks, masks) — that stays with the caller (test_harness.html's
// `captures` object today, the real frontend's equivalent later). This
// module only tracks *control flow*: which pose is active, how far along
// the user is, and what to show them.

import { POSE_KIND } from "./quality_gates.mjs";

export const CAPTURE_SEQUENCE = Object.freeze([POSE_KIND.FRONT, POSE_KIND.SIDE_STANDING, POSE_KIND.SIDE_SEATED]);

// Copy decided during the earlier product-design discussion
// (PRODUCT_ROADMAP_NOTES.md's "Body scan — capture protocol" section):
// clothing guidance is "form-fitting over loose" for everyone, Cd is never
// named/singled out, and the seated pose gets its own honest explanation
// tied to what it actually computes (seat height on press machines), not
// something invented like squat depth.
//
// `title`/`body` are shown on the capture screen during the pose; `hint`
// (one short line) and `why` (what it measures -> what it sets) are shown
// on the intro screen before the scan starts, so people know what's coming
// (scan.html's renderPoseOverview). Kept together so the two screens can't
// drift apart. `why` for the side-standing pose says "helps fit", not
// "sets": the engine doesn't consume torso depth yet.
export const POSE_INSTRUCTIONS = Object.freeze({
  [POSE_KIND.FRONT]: {
    title: "Stand facing the camera",
    body: "Full body in frame, arms slightly away from your sides. Form-fitting clothing gives a more accurate result than loose clothing.",
    hint: "Arms slightly away from your sides",
    why: "Measures your leg and arm lengths and shoulder width — used for leg-machine seats and pads, and to check the grip on the shoulder press.",
  },
  [POSE_KIND.SIDE_STANDING]: {
    title: "Turn side-on to the camera",
    body: "Full body in frame, arms relaxed at your sides. This pose measures the depth of your torso.",
    hint: "Arms relaxed at your sides",
    why: "Captures your torso profile, which helps fit chest-supported machines.",
  },
  [POSE_KIND.SIDE_SEATED]: {
    title: "Sit down side-on to the camera",
    body: "Sit on a chair with your back straight. This sets up seat height on machines — it isn't a measure of squat depth.",
    hint: "On a firm chair, back straight, feet flat",
    why: "Measures how high your shoulders sit when you're seated — that's what sets the seat height on chest press, shoulder press and pec deck, so you're not sinking below the handles or reaching up to them.",
  },
});

/** Fresh flow state: nothing captured yet, first pose in the sequence active. */
export function createCaptureFlow() {
  return { currentIndex: 0, completedPoseKinds: new Set() };
}

/** The pose the user should be capturing right now, or null once the whole
 * sequence is done (caller should move to the confirmation screen). */
export function currentPoseKind(flowState) {
  if (flowState.currentIndex < 0 || flowState.currentIndex >= CAPTURE_SEQUENCE.length) return null;
  return CAPTURE_SEQUENCE[flowState.currentIndex];
}

export function isFlowComplete(flowState) {
  return flowState.currentIndex >= CAPTURE_SEQUENCE.length;
}

/** e.g. "2 of 3" — clamped so it still reads sensibly once complete. */
export function progressText(flowState) {
  const step = Math.min(flowState.currentIndex + 1, CAPTURE_SEQUENCE.length);
  return `${step} of ${CAPTURE_SEQUENCE.length}`;
}

/** Instruction copy for the pose currently active, or null once complete. */
export function currentInstructions(flowState) {
  const poseKind = currentPoseKind(flowState);
  return poseKind ? POSE_INSTRUCTIONS[poseKind] : null;
}

/**
 * Advance to the next pose after a capture fires. Guards against
 * out-of-order/stale events (e.g. a capture callback that resolves after
 * the user already redid a different step) by only advancing if
 * `capturedPoseKind` matches the pose actually active right now —
 * otherwise the input state is returned unchanged.
 */
export function advanceAfterCapture(flowState, capturedPoseKind) {
  if (currentPoseKind(flowState) !== capturedPoseKind) return flowState;
  const completedPoseKinds = new Set(flowState.completedPoseKinds);
  completedPoseKinds.add(capturedPoseKind);
  return { currentIndex: flowState.currentIndex + 1, completedPoseKinds };
}

/** Jump back to redo an already-captured (or even the current) pose.
 * Caller is responsible for discarding that pose's stored measurement
 * data — this only rewinds the control-flow position. */
export function requestRedo(flowState, poseKindToRedo) {
  const index = CAPTURE_SEQUENCE.indexOf(poseKindToRedo);
  if (index === -1) return flowState;
  const completedPoseKinds = new Set(flowState.completedPoseKinds);
  completedPoseKinds.delete(poseKindToRedo);
  return { currentIndex: index, completedPoseKinds };
}

// ---------------------------------------------------------------------------
// Smoke test — same convention as scan/measurements.mjs and
// scan/quality_gates.mjs (Node-only guard, dynamic node:url import).
// Run: node scan/capture_flow.mjs
// ---------------------------------------------------------------------------

function assertEqual(actual, expected, label) {
  const a = actual instanceof Set ? [...actual].sort() : actual;
  const e = expected instanceof Set ? [...expected].sort() : expected;
  if (JSON.stringify(a) !== JSON.stringify(e)) {
    throw new Error(`${label}: expected ${JSON.stringify(e)}, got ${JSON.stringify(a)}`);
  }
}

if (typeof process !== "undefined" && process.versions && process.versions.node) {
  const { fileURLToPath } = await import("node:url");
  if (process.argv[1] === fileURLToPath(import.meta.url)) {
    // --- Fresh flow ---
    let flow = createCaptureFlow();
    assertEqual(currentPoseKind(flow), POSE_KIND.FRONT, "fresh flow starts on front");
    assertEqual(isFlowComplete(flow), false, "fresh flow not complete");
    assertEqual(progressText(flow), "1 of 3", "fresh flow progress");
    assertEqual(currentInstructions(flow) !== null, true, "fresh flow has instructions");
    console.log("fresh flow: OK");

    // --- Stale capture event ignored ---
    const staleIgnored = advanceAfterCapture(flow, POSE_KIND.SIDE_STANDING); // wrong pose for current step
    assertEqual(currentPoseKind(staleIgnored), POSE_KIND.FRONT, "stale capture event does not advance");
    console.log("stale capture ignored: OK");

    // --- Advance through the whole sequence ---
    flow = advanceAfterCapture(flow, POSE_KIND.FRONT);
    assertEqual(currentPoseKind(flow), POSE_KIND.SIDE_STANDING, "advances to side_standing after front");
    assertEqual(progressText(flow), "2 of 3", "progress after first capture");
    assertEqual(flow.completedPoseKinds, new Set([POSE_KIND.FRONT]), "front marked complete");

    flow = advanceAfterCapture(flow, POSE_KIND.SIDE_STANDING);
    assertEqual(currentPoseKind(flow), POSE_KIND.SIDE_SEATED, "advances to side_seated after side_standing");
    assertEqual(progressText(flow), "3 of 3", "progress after second capture");

    flow = advanceAfterCapture(flow, POSE_KIND.SIDE_SEATED);
    assertEqual(currentPoseKind(flow), null, "no current pose once flow complete");
    assertEqual(isFlowComplete(flow), true, "flow complete after third capture");
    assertEqual(progressText(flow), "3 of 3", "progress clamped once complete");
    assertEqual(currentInstructions(flow), null, "no instructions once complete");
    assertEqual(
      flow.completedPoseKinds,
      new Set([POSE_KIND.FRONT, POSE_KIND.SIDE_STANDING, POSE_KIND.SIDE_SEATED]),
      "all three marked complete",
    );
    console.log("full sequence advance: OK");

    // --- Redo rewinds to the right step and un-marks it complete ---
    const redone = requestRedo(flow, POSE_KIND.SIDE_STANDING);
    assertEqual(currentPoseKind(redone), POSE_KIND.SIDE_STANDING, "redo jumps back to requested pose");
    assertEqual(redone.completedPoseKinds, new Set([POSE_KIND.FRONT, POSE_KIND.SIDE_SEATED]), "redone pose un-marked complete");
    assertEqual(isFlowComplete(redone), false, "flow no longer complete after redo");

    // --- Redo with an unknown pose kind is a no-op ---
    const unknownRedo = requestRedo(flow, "not_a_real_pose");
    assertEqual(unknownRedo, flow, "redo with unknown pose kind is a no-op");
    console.log("redo: OK");

    // --- Every pose has all four pieces of copy (intro screen + capture screen) ---
    for (const poseKind of CAPTURE_SEQUENCE) {
      for (const key of ["title", "body", "hint", "why"]) {
        const text = POSE_INSTRUCTIONS[poseKind][key];
        assertEqual(typeof text === "string" && text.length > 0, true, `${poseKind}.${key} present`);
      }
    }
    console.log("pose copy complete: OK");

    console.log("\nAll scan/capture_flow.mjs smoke tests passed.");
  }
}
