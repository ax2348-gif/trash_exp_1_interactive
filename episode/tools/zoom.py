# zoom.py IMG X0 Y0 X1 Y1 SCALE OUT : crop + upscale with pixel ticks (labels in source pixels)
import sys
from PIL import Image, ImageDraw
src, x0, y0, x1, y1, k, out = sys.argv[1], *map(int, sys.argv[2:7]), sys.argv[7]
im = Image.open(src).convert("RGB").crop((x0, y0, x1, y1))
im = im.resize((im.width * k, im.height * k), Image.LANCZOS); d = ImageDraw.Draw(im)
for x in range((x0 // 10 + 1) * 10, x1, 10):
    X = (x - x0) * k; d.line([(X, 0), (X, 6 if x % 50 else 14)], fill=(255, 255, 0)); x % 50 or d.text((X + 2, 14), str(x), fill=(255, 255, 0))
for y in range((y0 // 10 + 1) * 10, y1, 10):
    Y = (y - y0) * k; d.line([(0, Y), (6 if y % 50 else 14, Y)], fill=(255, 255, 0)); y % 50 or d.text((16, Y - 5), str(y), fill=(255, 255, 0))
im.save(out)
