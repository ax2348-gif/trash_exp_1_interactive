# cloud.py: depth frame -> base-frame points, indexed by colour pixel.
#   python3 tools/cloud.py [N|latest] U0 V0 U1 V1 [STEP]  -> grid of x/y/z (base) at colour pixels in the box
import json, sys, glob, os, numpy as np
from PIL import Image
RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
C = json.load(open(f"{RUN}/streams/calibration.json")); T = np.array(json.load(open(f"{RUN}/robot.json"))["camera"]["base_to_color"])
def load(n="latest"):
    fs = sorted(glob.glob(f"{RUN}/streams/cam/*_depth.png")); f = fs[-1] if n == "latest" else f"{RUN}/streams/cam/{int(n):06d}_depth.png"
    d = np.asarray(Image.open(f)).astype(float) / 1000; D = C["depth"]; v, u = np.nonzero(d > 0.1); z = d[v, u]
    P = np.stack([(u - D["cx"]) / D["fx"] * z, (v - D["cy"]) / D["fy"] * z, z])
    R = np.array(C["depth_to_color"]["rotation"]); t = np.array(C["depth_to_color"]["translation_mm"]) / 1000
    Pc = R @ P + t[:, None]; K = C["color"]
    uc = K["fx"] * Pc[0] / Pc[2] + K["cx"]; vc = K["fy"] * Pc[1] / Pc[2] + K["cy"]
    Pb = T[:3, :3] @ Pc + T[:3, 3:4]
    return f, uc, vc, Pb.T
if __name__ == "__main__":
    a = sys.argv[1:]; f, uc, vc, Pb = load(a[0]); u0, v0, u1, v1 = map(int, a[1:5]); s = int(a[5]) if len(a) > 5 else 4
    print(os.path.basename(f), "rows: v, cols: u; cell = x,y,z (cm)")
    print("     " + " ".join(f"{u:>14d}" for u in range(u0, u1 + 1, s)))
    for v in range(v0, v1 + 1, s):
        row = []
        for u in range(u0, u1 + 1, s):
            m = (abs(uc - u) < s / 2) & (abs(vc - v) < s / 2)
            row.append("%4.1f,%5.1f,%4.1f" % tuple(np.median(Pb[m], 0) * 100) if m.sum() else " " * 14)
        print(f"{v:4d} " + " ".join(f"{c:>14s}" for c in row))
