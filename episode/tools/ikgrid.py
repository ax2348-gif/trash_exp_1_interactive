# ikgrid.py: IK reachability (no motion) for "x,y,z,r,p,yw" poses given as arguments
import sys, json; sys.path.insert(0, '/Users/aves/Documents/code/robot_utils/tools/agent_mm'); import mm
for a in sys.argv[1:]:
    v = list(map(float, a.split(','))); st, r = mm.call('arm', 'POST', 'ik', {"pose": {"pos": v[:3], "rpy": v[3:6]}})
    print(a, r.get('ok'), r.get('within_limits'), r.get('reason'), r.get('q') if r.get('ok') else '')
