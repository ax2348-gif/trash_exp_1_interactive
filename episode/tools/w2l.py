# w2l.py X Y [X Y ...]: world -> current base frame (pose from GET agent_nav/state, unlogged read)
import sys, json, math, urllib.request
s = json.load(urllib.request.urlopen("http://botcore-desktop.tail0fa175.ts.net/nodes/agent_nav/state"))
x0, y0, t = s["pose_world"]; c, si = math.cos(t), math.sin(t); print("pose", s["pose_world"])
a = list(map(float, sys.argv[1:]))
for X, Y in zip(a[::2], a[1::2]):
    dx, dy = X - x0, Y - y0; print((X, Y), "->", round(dx * c + dy * si, 3), round(-dx * si + dy * c, 3))
