# Improvised tools used in this episode

Everything the subagent wrote on the fly, plus what the parent session wrote afterwards for documentation. `#N` refers to the numbered
entries in [`tools/commands.md`](tools/commands.md): every shell command, file write and edit, extracted **verbatim** from
[`claude_transcript.jsonl`](claude_transcript.jsonl) (the subagent's transcript, unmodified) by `tools/extract_commands.py`, each with its result
(`ok` / `error` / `denied`).

The subagent started from the shared tools in `tools/agent_mm/`. The brief pointed it at `mm.py`, `record.py` and `ray.py`, and it didn't change any of them.

## 1. Robot calls and motion

| tool | created | what |
|---|---|---|
| `tools/mm` | #9 | Shell wrapper: runs `tools/agent_mm/mm.py` with `MM_RUN` set to this folder, so every call lands in `calls.jsonl` and `img/`. Used in ~105 entries. |
| `tools/leg.sh` | #97 | One base leg: post a nav goal, wait, print the result and recent robot events (reflex stops), read the gripper, look. |
| `tools/check.sh` | #99 | `plan/check` of a local goal; prints the warnings, the BEV, and the nearest flagged point converted to the robot frame (via `w2l.py`). Wrote a temporary file in `/tmp` and deleted it. |
| `tools/creep.py` | #102 | The operator-approved option (a), as code. Re-issues a global goal after each stop the robot's own load triggered, but only if three checks pass: a fresh look, a `plan/check` whose warnings and nearest point are the held block, and a depth check (`cloud.py`) that the band ahead has no points other than the block. Stops on anything else. Its first run stopped itself because the block window was too tight; the window was widened at #103–107. |
| `tools/servo_d.py` | #131 | `/servo` with an exact duration, for slow moves near the joint-1 singularity. Logs a RESULT row like `mm.py servo`. |
| `tools/track_x.py` | #138 | Leaves the joint-1 singularity by streaming `/track` poses in +x, 1 mm steps. Aborts on IK failure or a joint-1 jump > 0.08 rad. This is what finally worked after several refused `/servo` steps. |
| `tools/ikgrid.py` | #153 | IK reachability checks (no motion) for a list of poses. Last used, just before the stop, to probe poses down to the floor. |

## 2. Perception from the recorder's depth frames

The subagent used the high-rate recording (`streams/cam/`, 1 Hz) as a perception source next to the nav queries.

| tool | created | what |
|---|---|---|
| `tools/cloud.py` | #16 | Back-projects a recorded depth frame into base-frame points, indexed by colour pixel. Uses the calibrated depth intrinsics, the depth→colour extrinsic and `base_to_color`. Prints an x/y/z grid over a pixel box. Used for the block, gripper and can measurements. |
| `tools/selfcheck.py` | #98 | For the last K depth frames: points ahead of the bumper in the swept band, split into "block-like" and "other". Its only purpose was to decide whether a reflex stop was triggered by the held block or by something else. |
| `tools/topview.py` | #113 | Top-down PNG of the latest depth frame in a height band. Used to map the can's lid and slot (`img/s62_topview_lid.png`). |
| `tools/rx.py` | #31 | Colour pixel → base point on a vertical plane x = const, using the **calibrated** colour intrinsics (unlike `ray.py`'s FOV model); also `proj()`. |
| `tools/w2l.py` | #94 | World → current base frame, reading the pose from `GET agent_nav/state` (an unlogged read). |
| `tools/zoom.py` | #12 | Crop and upscale with pixel ticks labelled in source pixels. Made the 25 `img/sNN_zoom*.jpg` crops. |

Derived images in `img/` (beyond the API's snapshots, overlays and BEVs): `s30_zoom_block`, `s31_zoom_gripper`, `s32–s41_zoom`,
`s45/s46_zoom_bins`, `s46_zoom_far`, `s52_zoom_can`, `s54_zoom_right`, `s61_zoom_cantop`, `s62_topview_lid.png`, `s64_zoom_lid`,
`s66_zoom_before`, `s67_zoom_release`, `s68–s71_zoom`, and the robot diagrams `robot-*.png`. Every image the subagent opened is in `img/`.

## 3. Written after the run (parent session, for documentation)

| tool | what |
|---|---|
| `tools/extract_commands.py` | Copied from the pick-place episode. Generates `tools/commands.md` from the transcript. |
| `tools/decode_streams.py` | Decodes `streams/` (up to the episode end) into `streams/derived/`: `arm_50hz.csv`, `base_20hz.csv`, `gripper_events.csv`, `cam_thumbs/` (320×240), `cam_index.json`, and `review_10x.mp4` (every 1 Hz camera frame at 10 fps: colour with time, the agent's latest comment, arm and gripper state; depth; and a top-down world map accumulated from depth with the robot's path). Uses the repo's `common.protocol` reader and a pip-installed `imageio-ffmpeg` (bundled ffmpeg; nothing installed system-wide). |
| `tools/build_html.py` | Builds the replay pages (see README). |
| `tools/trim_streams.py` | Cuts the raw streams and camera frames at the episode end (21:45:12.237, the operator's "terminate the session") for publishing. `decode_streams.py` applies the same cutoff to everything it derives. |

## 4. Errors and denials (from `commands.md`)

Nine entries carry `error` or `denied`. The one denial is **#70, "Lower held block out of camera view and look"**. The permission classifier
refused it as weakening a safety mechanism (hiding the held block from the stop reflex). It was not retried in any form.
