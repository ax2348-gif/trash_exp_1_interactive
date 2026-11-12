#!/usr/bin/env python3
"""Post-run, read-only IK search: could the held block be (a) carried behind the bumper, (b) raised over the can's rim?

  python3 tools/ik_audit.py        (run from the episode folder; only POST /arm/ik, which moves nothing and needs no lease)

Held-block geometry, measured from the recording (streams/, tools/reflex_audit.py): while carried at TCP (0.033, 0, 0.633)
rpy 0, the block's far top edge was at base x ~0.215, z ~0.86. So relative to the TCP (arm frame = base axes, base z =
arm z + MOUNT_Z), in the tool frame: block x in [0.10, 0.18] (8 cm deep, far face 0.18 ahead), z in [-0.038, +0.037]
around the finger (7.5 cm tall), y in [-0.07, +0.01]. MOUNT_Z (arm z -> base z) is ~0.19-0.21 m; 0.20 is used and the
result is reported with that +-1 cm uncertainty. Pitch: negative = nose up (the agent's convention, rpy about y).
"""
import itertools, json, math, os, sys
import numpy as np
sys.path.insert(0, "/Users/aves/Documents/code/robot_utils/tools/agent_mm")
os.environ.setdefault("MM_RUN", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mm  # noqa: E402  (logged calls: every /ik query lands in calls.jsonl, tagged below)

MOUNT_Z = 0.20
BUMPER = 0.216
CORNERS = np.array(list(itertools.product([0.10, 0.18], [-0.07, 0.01], [-0.038, 0.037])))


def block_in_base(x, z, pitch):
    """Block corners in the base frame for TCP (x, 0, z) in arm frame and rpy (0, pitch, 0)."""
    c, s = math.cos(pitch), math.sin(pitch)
    R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])          # rotation about y by `pitch`
    P = CORNERS @ R.T
    return P + np.array([x, 0.0, z + MOUNT_Z])


def ik(x, z, p):
    st, r = mm.call("arm", "POST", "ik", {"pose": {"pos": [round(x, 3), 0.0, round(z, 3)], "rpy": [0.0, round(p, 3), 0.0]}})
    return bool(st == 200 and r.get("ok") and r.get("within_limits", True)), r


rows = []
grid = [(x, z, p) for x in np.arange(-0.04, 0.481, 0.03) for z in np.arange(0.44, 0.801, 0.03) for p in np.arange(0.0, -1.31, -0.15)]
for x, z, p in grid:
    ok, r = ik(x, z, p)
    B = block_in_base(x, z, p)
    rows.append(dict(x=round(x, 3), z=round(z, 3), pitch=round(p, 3), ok=ok, q=r.get("q") if ok else None,
                     block_low_z=round(float(B[:, 2].min()), 3), block_far_x=round(float(B[:, 0].max()), 3),
                     block_centre_x=round(float(B[:, 0].mean()), 3)))
out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "streams", "derived", "ik_audit.json")
json.dump(rows, open(out, "w"))
ok = [r for r in rows if r["ok"]]
print(f"{len(rows)} IK queries, {len(ok)} solvable")

# (a) carry: every block point >= 1.5 cm behind the bumper
carry = sorted([r for r in ok if r["block_far_x"] <= BUMPER - 0.015], key=lambda r: (abs(r["pitch"]), -r["z"]))
print("\n(a) carry poses with the whole block >= 1.5 cm behind the bumper:", len(carry))
for r in carry[:8]: print("   ", r["x"], r["z"], r["pitch"], "far_x", r["block_far_x"], "low_z", r["block_low_z"])

# (b) drop: lowest block point above the rim + margin; report the farthest block centre for each clearance
print("\n(b) farthest reachable block centre (base x) vs required lowest-point height:")
for need in (0.78, 0.80, 0.82, 0.84):
    c = [r for r in ok if r["block_low_z"] >= need]
    if c:
        b = max(c, key=lambda r: r["block_centre_x"])
        print(f"    low >= {need:.2f}: centre x {b['block_centre_x']:.3f} (far edge {b['block_far_x']:.3f}) at TCP x {b['x']}, z {b['z']}, pitch {b['pitch']}  [{len(c)} poses]")
    else:
        print(f"    low >= {need:.2f}: none")
lvl = [r for r in ok if r["pitch"] == 0.0]
print("\n    level only (pitch 0): max lowest point", max(r["block_low_z"] for r in lvl))
