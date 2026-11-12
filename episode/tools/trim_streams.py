#!/usr/bin/env python3
"""Cut this episode's raw stream recordings at the episode end, for publishing.

  python3 tools/trim_streams.py OUT_DIR       (run from the episode folder)

The episode ends at the operator's "terminate the session" (21:45:12.237 local); the recorder ran on to 21:46:09 during shutdown.
Writes OUT_DIR/streams/{arm,estimator}.bin with every row after the cutoff dropped (other records kept as they are; a rows record
that straddles the cutoff is re-packed with only its earlier rows), OUT_DIR/streams/cam/frames.jsonl with only the frames up to
the cutoff, and copies those frames' colour and depth files. streams/ in the episode folder stays the untrimmed capture.
"""
import json, os, shutil, sys
import numpy as np

EP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.abspath(os.path.join(EP, "..", "..", "..", "src")))
from robot_utils.nodes.common.protocol import iter_records, pack_record  # noqa: E402

CUTOFF = 1794365112.237          # 2026-11-11T02:45:12.237Z, the same cutoff as decode_streams.py
S = os.path.join(EP, "streams")
OUT = os.path.join(sys.argv[1], "streams")
OFF = json.load(open(os.path.join(S, "meta.json")))["estimator_epoch_minus_mono"]
os.makedirs(os.path.join(OUT, "cam"), exist_ok=True)

for name, tcol in (("arm.bin", "t_tick"), ("estimator.bin", "t")):
    schemas, kept, dropped = {}, 0, 0
    with open(os.path.join(OUT, name), "wb") as f:
        for h, payload in iter_records(open(os.path.join(S, name), "rb")):
            if h.get("type") == "schema":
                schemas[h.get("schema")] = h["fields"]
            if h.get("type") != "rows":
                f.write(pack_record(h, payload)); continue
            fields = h.get("fields") or schemas[h.get("schema")]
            a = np.frombuffer(payload, "<f8").reshape(-1, len(fields))
            m = a[:, fields.index(tcol)] + OFF <= CUTOFF
            kept += int(m.sum()); dropped += int((~m).sum())
            if m.all():
                f.write(pack_record(h, payload))
            elif m.any():
                f.write(pack_record({**h, "n": int(m.sum())}, np.ascontiguousarray(a[m]).tobytes()))
    print(f"{name}: kept {kept} rows, dropped {dropped}")

frames = [json.loads(l) for l in open(os.path.join(S, "cam", "frames.jsonl"))]
keep = [fr for fr in frames if fr["t_wall"] <= CUTOFF]
with open(os.path.join(OUT, "cam", "frames.jsonl"), "w") as f:
    for fr in keep:
        f.write(json.dumps(fr) + "\n")
for fr in keep:
    for suf in ("_color.jpg", "_depth.png"):
        shutil.copy2(os.path.join(S, "cam", f"{fr['n']:06d}{suf}"), os.path.join(OUT, "cam", f"{fr['n']:06d}{suf}"))
print(f"camera frames: kept {len(keep)} (0..{keep[-1]['n']}), dropped {len(frames) - len(keep)}")
