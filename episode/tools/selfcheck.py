# selfcheck.py [K]: last K depth frames; points ahead of the bumper in the swept band (x 0.2-0.5, |y|<0.32, z>0.05).
# Splits them into "block-like" (z>0.75, y<-0.15, x<0.26) and "other". Any "other" means a stop may NOT be self-triggered.
import sys, glob; sys.path.insert(0, __file__.rsplit('/', 1)[0]); import cloud, numpy as np
K = int(sys.argv[1]) if len(sys.argv) > 1 else 6
for f in sorted(glob.glob(cloud.RUN + '/streams/cam/*_depth.png'))[-K:]:
    n = f.split('/')[-1][:6]; _, uc, vc, P = cloud.load(n)
    m = (P[:, 0] > 0.2) & (P[:, 0] < 0.5) & (abs(P[:, 1]) < 0.32) & (P[:, 2] > 0.05)
    blk = m & (P[:, 2] > 0.75) & (P[:, 1] < -0.15) & (P[:, 0] < 0.26); oth = m & ~blk
    print(n, 'block', blk.sum(), 'other', oth.sum(), np.round(np.median(P[oth], 0), 3) if oth.sum() else '')
