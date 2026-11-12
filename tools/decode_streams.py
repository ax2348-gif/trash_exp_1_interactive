#!/usr/bin/env python3
"""Decode this episode's stream recordings (streams/) into derived files and a review video.

  python3 tools/decode_streams.py            (run from the episode folder; needs the repo's src/ and imageio-ffmpeg)

Inputs (written by tools/agent_mm/record.py during the run; these stay the canonical record):
  streams/arm.bin, streams/estimator.bin   raw framework streams (binary records; schema record first)
  streams/cam/NNNNNN_color.jpg, _depth.png, frames.jsonl, calibration.json, meta.json
Outputs (streams/derived/):
  arm_50hz.csv          arm telemetry, key columns, wall-clock time added
  base_20hz.csv         estimator pose / velocity at 20 Hz, wall-clock time added
  gripper_events.csv    every change of the gripper goal, with the gap and force reached
  cam_thumbs/NNNNNN.jpg 320x240 colour thumbnails (for the replay page), cam_index.json (frame -> wall time)
  review_10x.mp4        every recorded camera frame (1 Hz) played at 10 fps: colour | depth | top-down world map
"""
import csv, json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont

EP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.abspath(os.path.join(EP, "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
from robot_utils.nodes.common.protocol import iter_records, iter_rows  # noqa: E402

S = os.path.join(EP, "streams")
OUT = os.path.join(S, "derived")
os.makedirs(os.path.join(OUT, "cam_thumbs"), exist_ok=True)
meta = json.load(open(os.path.join(S, "meta.json")))
OFF = meta["estimator_epoch_minus_mono"]          # wall = Pi monotonic + OFF (same Pi clock for arm, estimator, camera)
# The episode ends when the operator said "terminate the session" (2026-11-11T02:45:12.237Z = 21:45:12.237 local). The recorder ran
# on to 21:46:09 during shutdown; that tail (camera frames 2139-2195, a person picking up the dropped block) is not part of the
# episode, so every derived output stops here. The raw files in streams/ are the untrimmed capture.
CUTOFF = 1794365112.237


def load(name):
    cols = None
    for _, rows in iter_rows(iter_records(open(os.path.join(S, name), "rb"))):
        if cols is None:
            cols = {k: [] for k in rows.dtype.names}
        for k in rows.dtype.names:
            cols[k].append(rows[k])
    cols = {k: np.concatenate(v) for k, v in cols.items()}
    tk = "t_tick" if "t_tick" in cols else "t"
    m = cols[tk] + OFF <= CUTOFF
    return {k: v[m] for k, v in cols.items()}


# ---------------------------------------------------------------- arm
arm = load("arm.bin")
ta = arm["t_tick"] + OFF
keep = (["state", "enabled", "servo", "x", "y", "z", "cmd_x", "cmd_y", "cmd_z", "err_pos", "err_rot", "w", "phase", "progress",
         "g_gap", "g_gap_cmd", "g_gap_goal", "g_force", "g_limiting"]
        + [f"j{i}_{f}" for i in range(1, 7) for f in ("q", "q_cmd", "tau", "tau_g", "tau_est")])
keep = [k for k in keep if k in arm]
with open(os.path.join(OUT, "arm_50hz.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t_wall", "t_mono"] + keep)  # units: m, rad, N, Nm (g_gap* in m), as in arm_fields.json
    for i in range(len(ta)):
        w.writerow([f"{ta[i]:.3f}", f"{arm['t_tick'][i]:.3f}"] + [f"{arm[k][i]:.5g}" for k in keep])
# gripper goal changes
ev, last = [], None
for i in range(len(ta)):
    g = arm["g_gap_goal"][i] * 1000          # stream units are metres
    if not np.isnan(g) and (last is None or abs(g - last) > 0.5):
        j = min(len(ta) - 1, i + 100)  # state 2 s later (50 Hz)
        ev.append([f"{ta[i]:.2f}", f"{g:.1f}", f"{arm['g_gap'][j] * 1000:.2f}", f"{arm['g_force'][j]:.2f}"])
        last = g
with open(os.path.join(OUT, "gripper_events.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t_wall", "gap_goal_mm", "gap_2s_later_mm", "force_2s_later_n"]); w.writerows(ev)

# ---------------------------------------------------------------- base
est = load("estimator.bin")
te = est["t"]
step = max(1, int(round(0.05 / np.median(np.diff(te)))))
with open(os.path.join(OUT, "base_20hz.csv"), "w", newline="") as f:
    w = csv.writer(f); w.writerow(["t_wall", "t_mono", "x", "y", "theta", "vx", "vy", "omega", "speed"])
    for i in range(0, len(te), step):
        w.writerow([f"{te[i] + OFF:.3f}", f"{te[i]:.3f}"] + [f"{est[k][i]:.5f}" for k in ("x", "y", "theta", "vx", "vy", "omega", "speed")])


def pose_at(tm):
    return (np.interp(tm, te, est["x"]), np.interp(tm, te, est["y"]), np.interp(tm, te, est["theta"]))


def arm_at(tw):
    i = min(len(ta) - 1, max(0, np.searchsorted(ta, tw)))
    return {k: arm[k][i] for k in ("x", "y", "z", "g_gap", "g_force", "enabled", "w")}


# ---------------------------------------------------------------- camera geometry
cal = json.load(open(os.path.join(S, "calibration.json")))
K = cal["depth"]; R_dc = np.array(cal["depth_to_color"]["rotation"]); t_dc = np.array(cal["depth_to_color"]["translation_mm"]) / 1000
T_bc = np.array(json.load(open(os.path.join(EP, "robot.json")))["camera"]["base_to_color"])
dec = 6
vv, uu = np.mgrid[0:K["height"]:dec, 0:K["width"]:dec]

# nav comments (what the agent said it was doing) for the overlay
comments = []
for l in open(os.path.join(EP, "calls.jsonl")):
    d = json.loads(l); b = d.get("body")
    if isinstance(b, dict) and b.get("comment"):
        comments.append((d["t"], f"{d['node']} {d['path']}: {b['comment']}"))
ct = np.array([c[0] for c in comments])

frames = [f for f in map(json.loads, open(os.path.join(S, "cam", "frames.jsonl"))) if f["t_wall"] <= CUTOFF]
for fn in os.listdir(os.path.join(OUT, "cam_thumbs")):      # drop thumbnails of frames past the cutoff
    if fn.endswith(".jpg") and int(fn[:6]) >= len(frames):
        os.remove(os.path.join(OUT, "cam_thumbs", fn))
if os.environ.get("LIMIT"):  # quick check: first N frames only
    frames = frames[:int(os.environ["LIMIT"])]
# world-map extent from the trajectory
X0, X1 = est["x"].min() - 2.0, est["x"].max() + 2.0
Y0, Y1 = est["y"].min() - 2.0, est["y"].max() + 2.0
MS = 480
mscale = MS / max(X1 - X0, Y1 - Y0)
to_px = lambda x, y: ((x - X0) * mscale, MS - (y - Y0) * mscale)   # world x right, world y up
acc = np.zeros((MS, MS, 3), np.float32)
cmap = __import__("matplotlib").colormaps["turbo"]
try:
    FONT = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 15)
    SMALL = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 12)
except Exception:
    FONT = SMALL = ImageFont.load_default()

ffmpeg = __import__("imageio_ffmpeg").get_ffmpeg_exe()
W, H = 640 + 640 + MS, 480 + 70
proc = subprocess.Popen([ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "10", "-i", "-",
                         "-c:v", "libx264", "-preset", "medium", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                         os.path.join(OUT, "review_10x.mp4")], stdin=subprocess.PIPE)
index, trail = [], []
t_start = frames[0]["t_wall"]
for fr in frames:
    n = fr["n"]; tw = fr["t_wall"]
    col = Image.open(os.path.join(S, "cam", f"{n:06d}_color.jpg")).convert("RGB")
    col.resize((320, 240), Image.LANCZOS).save(os.path.join(OUT, "cam_thumbs", f"{n:06d}.jpg"), quality=72)
    index.append({"n": n, "t_wall": round(tw, 3), "t_capture": fr["depth"].get("t_capture")})
    dm = np.asarray(Image.open(os.path.join(S, "cam", f"{n:06d}_depth.png")), dtype=np.float32)
    # depth panel
    dv = np.clip((dm - 200) / (3000 - 200), 0, 1)
    dimg = (cmap(dv)[..., :3] * 255).astype(np.uint8); dimg[dm == 0] = 0
    dpan = Image.fromarray(dimg).resize((640, 362), Image.NEAREST)
    # points -> base -> world
    z = dm[::dec, ::dec] / 1000.0
    ok = (z > 0.15) & (z < 4.0)
    xd = (uu[ok] - K["cx"]) * z[ok] / K["fx"]; yd = (vv[ok] - K["cy"]) * z[ok] / K["fy"]
    pd = np.stack([xd, yd, z[ok]], 1)
    pc = pd @ R_dc.T + t_dc
    pb = pc @ T_bc[:3, :3].T + T_bc[:3, 3]
    tm = fr["depth"].get("t_capture") or (tw - OFF)
    px, py, pth = pose_at(tm)
    c, s = math.cos(pth), math.sin(pth)
    wx = px + c * pb[:, 0] - s * pb[:, 1]; wy = py + s * pb[:, 0] + c * pb[:, 1]; hz = pb[:, 2]
    u, v = to_px(wx, wy)
    good = (u >= 0) & (u < MS) & (v >= 0) & (v < MS)
    ui, vi, hz_g = u[good].astype(int), v[good].astype(int), hz[good]
    acc *= 0.995
    rgb = np.where(hz_g[:, None] < 0.05, np.array([70, 70, 70]), (np.array(cmap(np.clip(hz_g / 1.5, 0, 1)))[:, :3] * 200))
    acc[vi, ui] = np.maximum(acc[vi, ui], rgb)
    mp = Image.fromarray(np.clip(acc, 0, 255).astype(np.uint8)); md = ImageDraw.Draw(mp)
    cur = Image.new("RGB", (MS, MS));
    md.point(list(zip(ui.tolist(), vi.tolist())), fill=(255, 255, 255))
    trail.append(to_px(px, py))
    if len(trail) > 1: md.line(trail, fill=(236, 64, 196), width=2)
    corners = [(0.216, 0.216), (0.216, -0.216), (-0.216, -0.216), (-0.216, 0.216)]
    md.polygon([to_px(px + c * a - s * b, py + s * a + c * b) for a, b in corners], outline=(255, 255, 255))
    hx, hy = to_px(px + c * 0.5, py + s * 0.5); ox, oy = to_px(px, py); md.line([(ox, oy), (hx, hy)], fill=(255, 255, 0), width=2)
    # compose
    can = Image.new("RGB", (W, H), (18, 18, 17)); can.paste(col, (0, 0)); can.paste(dpan, (640, 59)); can.paste(mp, (1280, 0))
    d = ImageDraw.Draw(can)
    el = tw - t_start
    lt = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(tw))
    a = arm_at(tw)
    k = np.searchsorted(ct, tw) - 1
    msg = comments[k][1] if k >= 0 else ""
    d.text((8, 488), f"{lt} local · +{int(el // 60):02d}:{int(el % 60):02d} · frame {n} · base ({px:.2f}, {py:.2f}, {(math.degrees(pth) + 180) % 360 - 180:.0f}°)", fill=(240, 240, 236), font=FONT)
    d.text((8, 508), f"arm {'on' if a['enabled'] > 0.5 else 'off'} · TCP ({a['x']:.3f}, {a['y']:.3f}, {a['z']:.3f}) · gripper {a['g_gap'] * 1000:.1f} mm, {a['g_force']:.1f} N", fill=(195, 194, 183), font=SMALL)
    d.text((8, 526), ("last comment: " + msg)[:190], fill=(160, 160, 150), font=SMALL)
    d.text((646, 6), "depth (0.2–3 m, turbo; black = no depth)", fill=(200, 200, 190), font=SMALL)
    d.text((1286, 6), "world map: depth so far (height colour), now white, path magenta", fill=(200, 200, 190), font=SMALL)
    proc.stdin.write(np.asarray(can, dtype=np.uint8).tobytes())
    if os.environ.get("LIMIT") and n == len(frames) - 1: can.save(os.path.join(OUT, "_check_frame.jpg"), quality=85)
proc.stdin.close(); proc.wait()
json.dump(index, open(os.path.join(OUT, "cam_index.json"), "w"))
print(f"arm rows {len(ta)} ({len(ta) / (ta[-1] - ta[0]):.1f} Hz), base rows {len(te)}, gripper events {len(ev)}, camera frames {len(frames)}")
