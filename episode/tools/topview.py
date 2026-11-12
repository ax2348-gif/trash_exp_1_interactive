# topview.py ZMIN ZMAX [OUT]: latest depth frame -> top-down PNG of points in a height band (base frame, 1 px = 1 cm,
# robot at bottom centre, x up, y left) + the colour image pixels' height colouring. Used to map the can's lid.
import sys, os; sys.path.insert(0, os.path.dirname(__file__)); import cloud, numpy as np
from PIL import Image, ImageDraw
z0, z1 = float(sys.argv[1]), float(sys.argv[2]); out = sys.argv[3] if len(sys.argv) > 3 else None
f, uc, vc, P = cloud.load('latest'); m = (P[:, 2] > z0) & (P[:, 2] < z1) & (P[:, 0] < 3.0)
W, H = 400, 320; im = Image.new('RGB', (W, H), (20, 20, 24)); d = ImageDraw.Draw(im)
for g in range(0, 300, 50): d.line([(0, H - g), (W, H - g)], fill=(60, 60, 60)); d.text((2, H - g - 10), f"x{g/100:.1f}", fill=(120, 120, 120))
for g in range(-200, 201, 50): d.line([(W // 2 - g, 0), (W // 2 - g, H)], fill=(60, 60, 60))
for p in P[m]:
    u, v = int(W // 2 - p[1] * 100), int(H - p[0] * 100)
    if 0 <= u < W and 0 <= v < H: t = (p[2] - z0) / (z1 - z0); im.putpixel((u, v), (int(255 * t), int(255 * (1 - t)), 80))
if out: im.resize((W * 2, H * 2)).save(out)
print(f, m.sum())
