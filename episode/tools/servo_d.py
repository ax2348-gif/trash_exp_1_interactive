# servo_d.py X Y Z R P Y DURATION: /servo with an exact duration (slow moves near the joint-1 singularity),
# wait, log a RESULT row like mm.py servo, and update mm.py's last goal.
import sys, os, json, time; sys.path.insert(0, '/Users/aves/Documents/code/robot_utils/tools/agent_mm'); import mm
v = list(map(float, sys.argv[1:8])); pos, rpy, dur = v[:3], v[3:6], v[6]
st, r = mm.call('arm', 'POST', 'servo', {"pose": {"pos": pos, "rpy": rpy}, "duration": dur})
if st != 200: print(st, r); sys.exit(1)
json.dump({"pos": pos, "rpy": rpy}, open(mm.GOAL, 'w')); time.sleep(dur + 1.5); now = mm.tcp()
out = {"goal": {"pos": pos, "rpy": rpy}, "measured": now["pos"], "rpy": now["rpy"], "err_m": [round(a - b, 4) for a, b in zip(now["pos"], pos)],
       "q": now["q"], "w": now["w"], "phase": now["motion"]["phase"], "gripper": now["gripper"]}
open(mm.LOG, 'a').write(json.dumps({"t": time.time(), "node": "arm", "method": "RESULT", "path": "servo", "resp": out}) + "\n"); print(json.dumps(out))
