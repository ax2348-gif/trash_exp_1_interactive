# Post-run audit: was the task blocked by the harness, or did the agent fail?

Written by the parent session after the run, from the recordings and the logs. The data is in `streams/derived/`, produced by
`tools/reflex_audit.py` and `tools/ik_audit.py`. The IK search used only `POST /arm/ik`, which moves nothing and needs no lease; its
queries are appended to `calls.jsonl`.

## 1. The reflex stops were the robot's own payload; a pitch would have fixed it

All seven REFLEX STOPs (goals 141–143, 145–148) were the held block and arm. In the recorded depth frame before each stop, every
reflex-zone point lies in the block/arm envelope and none outside it (`streams/derived/reflex_audit.json`):

| goals | arm TCP x | what the reflex saw |
|---|---|---|
| 141, 142 | 0.13, 0.09 | the block and gripper: thousands of points at x 0.22–0.32 m |
| 143, 146, 147, 148 | 0.033 | only the block's far top edge, at x 0.213–0.219 m and z ≈ 0.86, i.e. **0–3 mm past the bumper plane (0.216 m)**. 25–51 points, just over the 25-point threshold. The "0.05–0.06 m ahead" in some messages is the same edge measured along the diagonal motion direction (about −20°). |
| 145 | 0.033 | not reproduced: the recorded frame was 0.8 s old. The logged distance matches the same edge geometry. |

**Fix: a nose-up pitch.** The read-only IK search shows the block clears the bumper by a margin without crossing the joint-1
singularity. At the agent's own carry position (TCP x 0.02–0.05, z 0.62–0.65), a nose-up pitch of 0.45–0.9 rad moves the block's far
edge to 0.19–0.20 m, and to 0.15 m at 1.2 rad. The block also rises, staying in view, and the reflex correctly ignores anything behind
the bumper. The agent never pitched while carrying. Its only pitched move came after the release, over the floor.

The harness contributed:
- The reflex has no self-mask, so the robot's own payload counts as an obstacle.
- Near the singularity, `/servo` refused moves for "joint1 would exceed its speed limit". The message named the fix: a lower speed or a
  `duration`.

Neither was a hard blocker.

## 2. The drop was reachable with translation plus pitch; the agent's search stopped at its own grid edge

The agent's own search (21:34) was one grid of TCP x 0.12–0.30 × z 0.64–0.70 × nose-up pitch 0, 0.2, 0.4, 0.6. It never queried beyond
x 0.30, above z 0.70 at pitch 0.6, or past 0.6 rad. It then reported "IK solutions only out to TCP x ≈ 0.27–0.30" and "at or past the
limit": the edge of its grid, presented as the edge of the arm.

The post-run search covered x −0.04…0.48, z 0.44…0.80 and pitch 0…−1.3: 2,106 queries, 1,334 solvable. It used the held-block
geometry measured from the recording (block ~8 cm deep ending ~0.18 m ahead of the TCP, 7.5 cm tall around the finger) and an arm→base
z offset of 0.20 ± 0.01 m.

| block's lowest point at least | farthest reachable block centre (base x) | at TCP (x, z), pitch |
|---|---|---|
| 0.78 m | 0.586 | (0.47, 0.56), −0.60 |
| 0.80 m | 0.573 | (0.47, 0.56), −0.75 |
| 0.82 m | 0.543 | (0.44, 0.59), −0.75 |
| 0.84 m | 0.527 | (0.44, 0.59), −0.90 |

- **Within the agent's own window**, the best block centre was 0.424 m at the 0.80 m clearance.
- **Requirement:** rim front ≈ 0.76 m and back ≈ 0.80 m (the agent's noisy depth). With a reflex standoff of 0.13–0.15 m (the
  lookahead at 0.04–0.10 m/s), the slot edge 0.07–0.11 m behind the lid front, and the block centred in the 16 cm slot, the needed
  block centre is ≈ 0.50–0.56 m.
- **Result:** reachable at the 0.80 m clearance (0.573) with 1–7 cm to spare, before arm sag.
- **Order of operations:** approach with the block stowed (pitched, behind the bumper), stop, then extend. The reflex only runs while
  the base moves.

The best drop pose, q ≈ [0, −2.2, −2.55, −0.41, 0, 0], is far from upright; 15 of its 18 grid neighbours are also solvable.

The harness contributed: 42 of the agent's 124 IK queries failed, and 22 of those had position within 1 mm, missing only orientation
(by 3–8°). The tool still reported them as "out of reach or at a joint limit". A message that separates "position reachable,
orientation off by 4.9°" from "out of reach" would have shown that the boundary was the requested orientation, not the reach.

## Verdict

Nothing in the tools or harness made either problem insurmountable. The agent gave up early, and the harness made that easy:
- **Reflex:** a carry-pose problem (a few millimetres of the robot's own block past the bumper), fixable with a single pitch.
- **Drop:** feasible in IK with translation plus pitch. The agent's single coarse grid stopped at its own range limits, and it reported
  that edge as the arm's limit.
- **Harness friction:** no reflex self-mask, singularity speed refusals, and an IK failure message that says "out of reach" when only
  the orientation could not be matched.

## Caveats

- IK solvability is not proof of execution: the moves were not run. Not tested:
  - the path from the upright pose (large joint moves);
  - extra sag under the soft gains when fully extended (likely 1–2 cm or more);
  - collisions with the can's lid or with the robot itself.
- The block geometry (±1–2 cm), the can's rim and slot (noisy depth on black plastic), and the reflex standoff are estimates. The
  standoff was never tested at the can.
- Corroboration: the operator reports the task is doable by teleoperation, which uses the same IK.
