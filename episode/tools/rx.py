# rx.py X U,V ... : colour pixel -> base point on the vertical plane x = X (calibrated intrinsics, base_to_color from robot.json)
import json, sys, os, numpy as np
RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = np.array(json.load(open(f"{RUN}/robot.json"))["camera"]["base_to_color"]); K = json.load(open(f"{RUN}/streams/calibration.json"))["color"]
def rx(u, v, X):
    d = T[:3, :3] @ np.array([(u - K["cx"]) / K["fx"], (v - K["cy"]) / K["fy"], 1.0]); o = T[:3, 3]; return o + (X - o[0]) / d[0] * d
def proj(p):
    q = np.linalg.inv(T) @ np.r_[p, 1]; return K["fx"] * q[0] / q[2] + K["cx"], K["fy"] * q[1] / q[2] + K["cy"]
if __name__ == "__main__":
    X = float(sys.argv[1])
    for a in sys.argv[2:]:
        u, v = map(float, a.split(",")); print(a, np.round(rx(u, v, X), 3).tolist())
