#!/usr/bin/env python3
"""Reconstruct what the nav stop reflex saw at each REFLEX STOP, from the recorded depth frames.

  python3 tools/reflex_audit.py      (run from the episode folder)

The reflex rule (src/robot_utils/nodes/agent_nav/node.py, _reflex_tick): points with 0.04 < z < 1.6 m (base frame),
along the motion direction between the bumper (HALF = 0.216 m) and HALF + lookahead, and within HALF + 0.03 m sideways;
>= 25 points -> stop. This applies the same rule to the recorded depth frames (1 Hz, full 848x480, so counts are larger than
the reflex's own grid) taken just before each stop, and reports where the hit points are, split into the robot's own
arm / held block (an envelope around the gripper, from the arm stream's TCP at that moment) and everything else.
"""
import json, math, os, sys
import numpy as np
from PIL import Image

EP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
S = os.path.join(EP, "streams")
sys.path.insert(0, os.path.join(EP, "..", "..", "..", "src"))
from robot_utils.nodes.common.protocol import iter_records, iter_rows  # noqa: E402

HALF, Z = 0.216, (0.04, 1.6)
cal = json.load(open(os.path.join(S, "calibration.json")))
K = cal["depth"]; R = np.array(cal["depth_to_color"]["rotation"]); t = np.array(cal["depth_to_color"]["translation_mm"]) / 1000
T = np.array(json.load(open(os.path.join(EP, "robot.json")))["camera"]["base_to_color"])
vv, uu = np.mgrid[0:K["height"], 0:K["width"]]
frames = [json.loads(l) for l in open(os.path.join(S, "cam", "frames.jsonl"))]
fcap = np.array([f["depth"]["t_capture"] for f in frames])


def rows(name):
    out = None
    for _, r in iter_rows(iter_records(open(os.path.join(S, name), "rb"))):
        out = {k: [] for k in r.dtype.names} if out is None else out
        for k in r.dtype.names: out[k].append(r[k])
    return {k: np.concatenate(v) for k, v in out.items()}


arm, est = rows("arm.bin"), rows("estimator.bin")
log = [json.loads(l) for l in open(next(os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(EP, "nav_session")) for f in fs if f == "log.jsonl"))]
stops = [r for r in log if r["kind"] == "event" and "REFLEX STOP" in (r.get("reply") or {}).get("message", "")]
goal_of = {}
for r in log:
    m = (r.get("reply") or {}).get("message", "")
    if m.startswith("goal ") and "stopped" in m:
        goal_of.setdefault(round(r["t"]), r["reply"]["goal_id"])

out = []
for s in stops:
    rep = s["reply"]; tm = s["t"]
    msg = rep["message"]
    look = float(msg.split("braking distance (")[1].split(" m")[0]); vmsg = float(msg.split(" at ")[1].split(" m/s")[0])
    k = int(np.searchsorted(fcap, tm)) - 1                      # last depth frame captured before the stop
    f = frames[k]
    dm = np.asarray(Image.open(os.path.join(S, "cam", f"{f['n']:06d}_depth.png")), np.float32) / 1000
    ok = dm > 0
    z = dm[ok]; x = (uu[ok] - K["cx"]) * z / K["fx"]; y = (vv[ok] - K["cy"]) * z / K["fy"]
    pb = (np.stack([x, y, z], 1) @ R.T + t) @ T[:3, :3].T + T[:3, 3]
    i = int(np.searchsorted(est["t"], tm)); vx, vy = est["vx"][i], est["vy"][i]
    ang = math.atan2(vy, vx) if math.hypot(vx, vy) > 0.02 else 0.0
    c, sn = math.cos(ang), math.sin(ang)
    a = c * pb[:, 0] + sn * pb[:, 1]; b = -sn * pb[:, 0] + c * pb[:, 1]
    hit = (pb[:, 2] > Z[0]) & (pb[:, 2] < Z[1]) & (a > HALF) & (a < HALF + look) & (np.abs(b) < HALF + 0.03)
    H = pb[hit]
    j = int(np.searchsorted(arm["t_tick"], tm)); tcp = (arm["x"][j], arm["y"][j], arm["z"][j]); gap = arm["g_gap"][j] * 1000
    # own-arm / held-block envelope (base frame): fingertip ~ TCP + (0.17, -0.19, 0.19); block spans ~ +-0.06 around it
    tip = np.array([tcp[0] + 0.17, tcp[1] - 0.19, tcp[2] + 0.19])
    own = (np.abs(H[:, 0] - tip[0]) < 0.12) & (np.abs(H[:, 1] - tip[1]) < 0.10) & (H[:, 2] > tip[2] - 0.12) & (H[:, 2] < tip[2] + 0.10)
    O = H[~own]
    row = dict(goal=goal_of.get(round(tm)) or goal_of.get(round(tm) + 1), reflex_points=rep["points"], reflex_near_m=rep["distance_m"],
               v=vmsg, lookahead=look, motion_deg=round(math.degrees(ang)), frame=f["n"], frame_age_s=round(tm - fcap[k], 2),
               tcp=[round(v, 3) for v in tcp], gripper_mm=round(float(gap), 1), hits=int(hit.sum()), own=int(own.sum()), other=int((~own).sum()))
    if len(H):
        row["hits_x_y_z_5_95"] = [[round(float(q), 3) for q in np.percentile(H[:, d], [5, 95])] for d in range(3)]
    if len(O):
        row["other_x_y_z_5_50_95"] = [[round(float(q), 3) for q in np.percentile(O[:, d], [5, 50, 95])] for d in range(3)]
    out.append(row)
    print(json.dumps(row))
json.dump(out, open(os.path.join(EP, "streams", "derived", "reflex_audit.json"), "w"), indent=1)
