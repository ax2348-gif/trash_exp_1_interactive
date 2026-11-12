# Raw data: foam block → trash can episode (2026-11-10)

This `raw-data` branch holds the episode's raw recordings. It is an orphan branch: no shared history with `main`, which carries
only the replay page (GitHub Pages builds `main`). Fetch just this branch with:

```bash
git clone --single-branch --branch raw-data git@github.com:ax2348-gif/trash_exp_1_interactive.git
```

The recordings were made client-side by `record.py` during the run (from 21:09 local). They are cut at the episode end, the operator's
"terminate the session" at 21:45:12.237 local (2026-11-11T02:45:12.237Z), by `tools/trim_streams.py`. The recorder itself ran on for ~57 s
during shutdown; that tail is not part of the episode and is not published. The episode's narrative, tools, interview and call log are on
`main` under `episode/`.

## Inventory

| path | what | format |
|---|---|---|
| `streams/arm.bin.gz` | **arm telemetry incl. the TCP stream**, ~49 Hz, 120 fields: measured TCP `x y z qx qy qz qw`, commanded `cmd_x/y/z`, tracking error, manipulability, per-joint `q`, `q_cmd`, `qd`, `tau`, `tau_g`, `tau_est`, gripper `g_gap*` (m), `g_force` (N), motion phase | gzip of the framework's binary stream (below) |
| `streams/estimator.bin.gz` | base pose estimator, ~100 Hz: `x y theta`, velocities, odometry, IMU flags | same |
| `streams/arm_fields.json`, `estimator_fields.json` | field names, units and docs for the two streams | JSON |
| `streams/meta.json` | recorder start time and `estimator_epoch_minus_mono`: **wall time = Pi monotonic time + this offset**. The arm, estimator and camera all use the same Pi monotonic clock | JSON |
| `streams/calibration.json` | camera intrinsics (depth and colour) and the depth→colour extrinsic | JSON |
| `robot.json` | the robot description at the time, incl. `camera.base_to_color` (colour-optical → base frame) | JSON |
| `streams/cam/NNNNNN_depth.png` | 2,139 depth frames (#0–#2138), 848×480, 16-bit, millimetres (0 = no depth), ~1 Hz | PNG |
| `streams/cam/NNNNNN_color.jpg` | 2,139 colour frames, 640×480, ~1 Hz | JPEG |
| `streams/cam/frames.jsonl` | one line per frame: `n`, client `t_wall`, and the camera's frame headers (`t_capture` on the Pi monotonic clock, `seq`, …) | JSON lines |
| `streams/derived/arm_50hz.csv.gz` | decoded arm telemetry (key columns) with `t_wall` | gzip CSV |
| `streams/derived/base_20hz.csv.gz` | decoded base pose at 20 Hz with `t_wall` | gzip CSV |
| `streams/derived/gripper_events.csv`, `cam_index.json` | gripper goal changes, and camera frame → wall time | CSV, JSON |
| `calls.jsonl` | every robot HTTP call of the run, with responses, plus servo `RESULT` rows (also on `main`) | JSON lines |
| `calls_post_run_audit_ik.jsonl` | 2,106 read-only arm `/ik` checks made after the run by a separate audit session | JSON lines |
| `nav_session/` | agent_nav's own export of session `20261110-210932`: transcript of nav turns and thumbnails | as exported |
| `logs/record.log`, `logs/keeper.log` | recorder and lease-keeper output | text |
| `tools/protocol.py` | the stream reader from `robot_utils` (`src/robot_utils/nodes/common/protocol.py`); needs only numpy | Python |
| `tools/decode_streams.py` | the script that produced `streams/derived/` and the review video (same cutoff) | Python |
| `tools/trim_streams.py` | the script that cut `streams/` at the episode end | Python |
| `SHA256SUMS.original` | SHA-256 of the four uncompressed (trimmed) files | text |

**Not included:** the agent's raw Claude transcript (`claude_transcript.jsonl`), because its session metadata contains the account email. The
replay page on `main` shows its content.

## Reading the streams

Each `.bin` is the framework's recording format: a sequence of records, each `[u32 big-endian header length N][N-byte JSON header][payload]`.
The first record is the schema (field names). `rows` records carry little-endian float64 arrays of shape (n, n_fields).

```python
import gzip, sys
sys.path.insert(0, "tools")
from protocol import iter_records, iter_rows

for header, rows in iter_rows(iter_records(gzip.open("streams/arm.bin.gz", "rb"))):
    t, x, y, z = rows["t_tick"], rows["x"], rows["y"], rows["z"]      # Pi monotonic s; TCP in the arm base frame (m)
```

To restore the originals, run `gunzip -k streams/*.bin.gz streams/derived/*.csv.gz`. Then check them with `shasum -a 256 -c SHA256SUMS.original`.

**Ego point cloud for camera frame n:**
1. Back-project `NNNNNN_depth.png` with `calibration.json["depth"]`.
2. Apply `depth_to_color` (translation in mm).
3. Apply `robot.json` `camera.base_to_color`.
4. Place it in the world frame with the estimator pose interpolated at `frames.jsonl[n].depth.t_capture`.

`tools/decode_streams.py` does exactly this for its top-down map.

## Verified when uploaded

- **Compression:** the four compressed files decompress byte-identical to the trimmed files listed in `SHA256SUMS.original`.
- **Camera files:** frames #0–#2138 (the last at 21:45:12.04), each identical to the source episode folder.
- **Arm stream:** `arm.bin.gz` decodes with `tools/protocol.py` to 105,051 rows (48.8 Hz over 35.9 min), the last at 21:45:12.23.
