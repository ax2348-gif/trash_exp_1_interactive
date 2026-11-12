# creep.py X Y THETA [N]: operator-approved option (a). Re-issue a GLOBAL goal (<= ~1 m leg) after self-triggered
# reflex stops. Before EACH re-issue: look (images saved), plan/check (warnings + nearest point must be the held block),
# and a depth check of the swept band ahead (no non-block points above 3 cm). Stops on anything else.
import sys, os, json, math, time
sys.path.insert(0, '/Users/aves/Documents/code/robot_utils/tools/agent_mm'); sys.path.insert(0, os.path.dirname(__file__))
import mm, cloud, numpy as np
X, Y, TH = map(float, sys.argv[1:4]); N = int(sys.argv[4]) if len(sys.argv) > 4 else 8
def local(pw, x, y):
    c, s = math.cos(pw[2]), math.sin(pw[2]); dx, dy = x - pw[0], y - pw[1]; return dx * c + dy * s, -dx * s + dy * c
def block_like(p): return 0.10 < p[0] < 0.27 and -0.30 < p[1] < -0.12
for i in range(N):
    st, lk = mm.call('nav', 'POST', 'look', {"grid": True, "comment": f"creep {i}: look before re-issuing"}); mm.fetch_images(lk)
    pw = lk['pose_world']; lx, ly = local(pw, X, Y); dist = math.hypot(lx, ly)
    st, ck = mm.call('nav', 'POST', 'plan/check', {"frame": "global", "x": X, "y": Y, "theta": TH, "comment": f"creep {i}: check"}); mm.fetch_images(ck)
    c = ck['check']; w = c['warnings']; near = c.get('nearest_in_path_world') or []
    nl = [local(pw, *p) for p in near]
    bad_w = [x for x in w if not (x.startswith('OBSTACLE') or x.startswith('UNVERIFIED'))]
    _, uc, vc, P = cloud.load('latest')
    cl, sl = math.cos(math.atan2(ly, lx)), math.sin(math.atan2(ly, lx))
    a = P[:, 0] * cl + P[:, 1] * sl; b = -P[:, 0] * sl + P[:, 1] * cl          # along / across the leg direction
    band = (a > 0.2) & (a < dist + 0.4) & (abs(b) < 0.27) & (P[:, 2] > 0.03)
    blk = band & (P[:, 2] > 0.75) & (P[:, 0] < 0.27) & (P[:, 1] < -0.12)
    other = band & ~blk
    print(f"[{i}] {lk['snapshot']} pose {pw} remaining {dist:.3f} warn {[x[:40] for x in w]} nearest_local {[tuple(round(v,3) for v in p) for p in nl]} depth other {other.sum()}", flush=True)
    if dist < 0.03: print('at goal'); break
    if bad_w or (nl and not all(block_like(p) for p in nl)) or other.sum() > 5:
        print('STOP: not clearly self-only', np.round(np.median(P[other], 0), 3) if other.sum() else ''); break
    st, g = mm.call('nav', 'POST', 'goal', {"frame": "global", "x": X, "y": Y, "theta": TH, "speed": 0.08,
        "comment": f"creep {i}: re-issue after self-triggered reflex stop (look {lk['snapshot']}: only held-block points ahead; operator approved option a)"})
    if st != 200: print('goal refused', st, g); break
    st, r = mm.call('nav', 'GET', f"goals/{g['goal_id']}/wait?timeout=90"); res = r['result']
    st, lg = mm.call('nav', 'GET', 'log?since=0', log=False)
    ev = [e['reply'].get('message') for e in lg['turns'][-3:] if e['actor'] == 'robot']
    print('   ->', res['result'], res.get('reason'), ev, flush=True)
    if res['result'] == 'reached': print('reached'); break
    if not (res['result'] == 'stopped' and any(m and m.startswith('REFLEX STOP') for m in ev)): print('STOP: not a reflex stop'); break
    t = mm.tcp(); print('   gripper', t['gripper'])
    if t['gripper']['gap_mm'] < 3: print('STOP: block may be lost'); break
