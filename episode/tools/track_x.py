# track_x.py X_END [STEP_M] [DT]: leave the joint-1 singularity with /track (IK from the previous goal), moving the TCP
# in +x at constant y/z/rpy in small steps; aborts (/cancel) on IK failure or a joint-1 jump > 0.08 rad.
import sys, time, json; sys.path.insert(0, '/Users/aves/Documents/code/robot_utils/tools/agent_mm'); import mm
xe = float(sys.argv[1]); step = float(sys.argv[2]) if len(sys.argv) > 2 else 0.001; dt = float(sys.argv[3]) if len(sys.argv) > 3 else 0.1
t0 = mm.tcp(); x, y, z = t0['pos']; rpy = [0.0, 0.0, 0.0]; q1 = t0['q'][0]; y, z = 0.0, 0.633
print('start', t0['pos'], t0['q'])
while x < xe:
    x = min(xe, x + step)
    st, r = mm.call('arm', 'POST', 'track', {"pose": {"pos": [round(x, 4), y, z], "rpy": rpy}})
    if st != 200 or not r.get('ok', True): print('track fail', st, r); mm.call('arm', 'POST', 'cancel'); break
    time.sleep(dt)
    t = mm.tcp()
    if abs(t['q'][0] - q1) > 0.08: print('q1 jump', q1, t['q']); mm.call('arm', 'POST', 'cancel'); break
    q1 = t['q'][0]
    if round(x * 1000) % 10 == 0: print(round(x, 3), t['pos'], t['q'], t['w'], flush=True)
time.sleep(1.0); t = mm.tcp(); print('end', t['pos'], t['q'], t['w'], t['state'], t['gripper'])
json.dump({"pos": [round(x, 4), y, z], "rpy": rpy}, open(mm.GOAL, 'w'))
