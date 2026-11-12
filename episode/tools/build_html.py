#!/usr/bin/env python3
"""Build the replay pages for this episode (foam block -> trash can, 2026-11-10).

  python3 tools/build_html.py   (any cwd)

Adapted from the pick-place episode's tools/build_html.py (same look, layout, light/dark handling and
replay behaviour), extended with the episode's high-rate stream recordings in streams/derived/
(written by tools/decode_streams.py):
  base_20hz.csv   -> base trajectory          arm_50hz.csv      -> arm plot (binned to 4 Hz for display)
  cam_thumbs/     -> camera card, "recorded"  review_10x.mp4    -> recording video card (frame n = n / 10 s)
  cam_index.json  -> frame -> wall time       gripper_events.csv-> gripper marks on the arm plot

Reads claude_transcript.jsonl, calls.jsonl, README.md, TOOLS.md, INTERVIEW.md and tools/commands.md.
Writes:
  index.html                                relative paths (img/..., streams/...), nothing copied
  pick-place-2026-11-10-trash-can.html      standalone: images, thumbnails and data embedded; the video
                                            only if review_10x.mp4 is under VIDEO_EMBED_MAX
The transcript is rendered in file order from the brief through the stop: every user message, assistant
text, thinking marker, tool call and tool result; long outputs are collapsed behind <details>, never
shortened. The post-experiment interview after the stop is replaced by a visible "omitted" marker (it is
in INTERVIEW.md and on the Interview tab). Harness bookkeeping rows (api-request*, attachment
snapshots) are not shown.
"""
import base64, csv, datetime as dt, html, json, math, os, re

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = lambda *a: os.path.join(HERE, *a)
DER = P("streams", "derived")
TZ = dt.timezone(dt.timedelta(hours=-5))  # EST, local time of the run
esc = lambda s: html.escape(str(s), quote=True)
SA_NAME = "pick-place-2026-11-10-trash-can.html"
VIDEO_EMBED_MAX = 40e6     # bytes; a larger review_10x.mp4 ships alongside instead of being embedded
SA_MAX = 80e6              # standalone budget; above it, only every 2nd thumbnail is embedded
ARM_BIN = 0.25             # s; arm plot display rate 4 Hz


def iso2t(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def clock(t):
    return dt.datetime.fromtimestamp(t, TZ).strftime("%H:%M:%S")


# ---------------------------------------------------------------- mini markdown
def inline(s):
    links = []

    def keep(m):
        links.append(f'<a href="{esc(m.group(2))}">{inline(m.group(1))}</a>')
        return f"\x00{len(links) - 1}\x00"
    s = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", keep, s)
    r = _inline(s)
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], r)


def _inline(s):
    codes = []

    def keep(m):
        codes.append("<code>" + esc(m.group(0).strip("`")) + "</code>")
        return f"\x01{len(codes) - 1}\x01"
    p = esc(re.sub(r"`+[^`]*?`+", keep, s))
    p = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", p)
    p = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", p)
    return re.sub(r"\x01(\d+)\x01", lambda m: codes[int(m.group(1))], p)


def md(text, inl=inline, details=False):
    """details=True (docs only, never the transcript): pass README's <details>/<summary> lines through."""
    lines = text.split("\n")
    out, i, n = [], 0, len(lines)
    para = []

    def flush():
        if para:
            out.append("<p>" + inl(" ".join(x.strip() for x in para)) + "</p>")
            para.clear()

    while i < n:
        ln = lines[i]
        if details:
            dm = re.match(r"^\s*<details>\s*(?:<summary>(.*)</summary>)?\s*$", ln)
            if dm:
                flush(); out.append("<details class='mdd'><summary>" + inl(dm.group(1) or "details") + "</summary>"); i += 1; continue
            if re.match(r"^\s*</details>\s*$", ln):
                flush(); out.append("</details>"); i += 1; continue
        m = re.match(r"^(\s*)(`{3,})(.*)$", ln)
        if m:
            flush()
            fence, body = m.group(2), []
            i += 1
            while i < n and not re.match(r"^\s*" + fence + r"\s*$", lines[i]):
                body.append(lines[i]); i += 1
            i += 1
            out.append("<pre>" + esc("\n".join(body)) + "</pre>")
            continue
        if not ln.strip():
            flush(); i += 1; continue
        h = re.match(r"^(#{1,6})\s+(.*)$", ln)
        if h:
            flush()
            lv = min(6, len(h.group(1)) + 1)
            out.append(f"<h{lv}>{inl(h.group(2))}</h{lv}>"); i += 1; continue
        if ln.lstrip().startswith("|") and i + 1 < n and re.match(r"^\s*\|[\s:|-]+\|\s*$", lines[i + 1]):
            flush()
            cells = lambda l: [c.strip() for c in l.strip().strip("|").split("|")]
            hdr = cells(ln); i += 2; body = []
            while i < n and lines[i].lstrip().startswith("|"):
                body.append(cells(lines[i])); i += 1
            t = "<div class='tw'><table><thead><tr>" + "".join(f"<th>{inl(c)}</th>" for c in hdr) + "</tr></thead><tbody>"
            t += "".join("<tr>" + "".join(f"<td>{inl(c)}</td>" for c in r) + "</tr>" for r in body)
            out.append(t + "</tbody></table></div>")
            continue
        if re.match(r"^\s*([-*]|\d+[.)])\s+", ln):
            flush()
            block = []
            while i < n and (re.match(r"^\s*([-*]|\d+[.)])\s+", lines[i]) or (lines[i].startswith("  ") and lines[i].strip())):
                block.append(lines[i]); i += 1
            out.append(render_list(block, inl))
            continue
        para.append(ln); i += 1
    flush()
    return "\n".join(out)


def render_list(block, inl):
    ind = lambda l: len(l) - len(l.lstrip())
    base = ind(block[0])
    ordered = bool(re.match(r"^\s*\d+[.)]", block[0]))
    items, cur = [], None
    for l in block:
        if ind(l) <= base and re.match(r"^\s*([-*]|\d+[.)])\s+", l):
            cur = [re.sub(r"^\s*([-*]|\d+[.)])\s+", "", l)]
            items.append(cur)
        else:
            cur.append(l)
    tag = "ol" if ordered else "ul"
    start = ""
    if ordered:
        k = int(re.match(r"^\s*(\d+)", block[0]).group(1))
        if k != 1: start = f" start='{k}'"
    html_items = []
    for it in items:
        head, rest = it[0], it[1:]
        sub = [l for l in rest if re.match(r"^\s*([-*]|\d+[.)])\s+", l)]
        txt = [head] + [l.strip() for l in rest[: rest.index(sub[0])]] if sub else [head] + [l.strip() for l in rest]
        s = inl(" ".join(txt))
        if sub:
            s += render_list(rest[rest.index(sub[0]):], inl)
        html_items.append(f"<li>{s}</li>")
    return f"<{tag}{start}>" + "".join(html_items) + f"</{tag}>"


# ---------------------------------------------------------------- calls
calls_all = [json.loads(l) for l in open(P("calls.jsonl"))]
# The run ends when the parent session closes the nav session (DELETE session). calls.jsonl kept growing after
# that (post-run arm /ik checks, no motion, logged into the same file); those are counted and noted, not replayed.
CALLS_END = next(c["t"] for c in calls_all if c["method"] == "DELETE" and c["path"] == "session")
calls = [c for c in calls_all if c["t"] <= CALLS_END + 1]
post_calls = calls_all[len(calls):]
assert all(c["t"] > CALLS_END + 1 for c in post_calls)
imgs = set(os.listdir(P("img")))


def img_of(path):
    """images/s5/grid.jpg -> s5_grid.jpg ; images/s5-16.jpg -> s5-16.jpg (only if it exists)."""
    b = path.split("images/", 1)[-1]
    b = b.replace("/grid.jpg", "_grid.jpg")
    return b if b in imgs else None


def find_imgs(o, acc):
    if isinstance(o, dict):
        for v in o.values(): find_imgs(v, acc)
    elif isinstance(o, list):
        for v in o: find_imgs(v, acc)
    elif isinstance(o, str) and o.startswith("images/"):
        f = img_of(o)
        if f and f not in acc: acc.append(f)
    return acc


def mm(v): return f"{v * 1000:+.1f}"


C = []
waits = {}
for c in calls:
    p = c["path"]
    if p.startswith("goals/") and "/wait" in p:
        waits[p.split("/")[1]] = c
for c in calls:
    b, r, p = c.get("body") or {}, c.get("resp") or {}, c["path"]
    s = ""
    if c["method"] == "RESULT":
        g, e = r["goal"]["pos"], r["err_m"]
        s = f"goal ({g[0]:.3f}, {g[1]:.3f}, {g[2]:.3f}) · err x {mm(e[0])} y {mm(e[1])} z {mm(e[2])} mm · {r.get('phase','')} · gap {r.get('gripper',{}).get('gap_mm')} mm"
    elif isinstance(b, dict) and b.get("comment"):
        s = b["comment"]
    elif p == "servo" and isinstance(b, dict):
        s = json.dumps(b, separators=(",", ":"))
    elif p.startswith("goals/"):
        rr = r.get("result") or {}
        s = f"{rr.get('result','')} {('· ' + rr['reason']) if rr.get('reason') else ''}"
    elif b:
        s = json.dumps(b, separators=(",", ":"))
    if p.startswith("look") or p.startswith("query"):
        if r.get("snapshot"): s = f"{r['snapshot']} · " + s
    C.append({"t": round(c["t"], 3), "node": c["node"], "m": c["method"], "p": p, "st": c.get("status"),
              "s": s[:240], "img": find_imgs(r, [])})

looks = []
for c in calls:
    if c["path"] == "look" and c.get("status") == 200:
        r = c["resp"]
        looks.append({"t": round(c["t"], 3), "id": r["snapshot"], "pose": r.get("pose_world"),
                      "img": img_of(r.get("image", "")), "bev": img_of(r.get("bev", "")),
                      "grid": img_of(r.get("grid_image", "")) if r.get("grid_image") else None,
                      "c": (c.get("body") or {}).get("comment", "")})
goals = []
for c in calls:
    if c["path"] == "goal":
        r, b = c["resp"], c["body"]
        w = waits.get(str(r.get("goal_id")))
        res = ((w or {}).get("resp") or {}).get("result") or {}
        goals.append({"t": round(c["t"], 3), "id": r.get("goal_id"), "to": r["goal"]["world"], "from": r["goal"]["from_world"],
                      "res": res.get("result"), "why": res.get("reason", ""), "end": round(w["t"], 3) if w else None,
                      "c": b.get("comment", "")})
servo = []
for c in calls:
    if c["method"] == "RESULT":
        r = c["resp"]
        servo.append({"t": round(c["t"], 3), "g": r["goal"]["pos"], "m": [round(v, 5) for v in r["measured"]],
                      "e": r["err_m"], "ph": r.get("phase"), "gap": (r.get("gripper") or {}).get("gap_mm")})
grips = [{"t": round(c["t"], 3), "gap": c["body"]["gap_mm"], "f": c["body"].get("max_force_n"),
          "after": (c.get("resp") or {}).get("gap_mm")} for c in calls if c["path"] == "gripper" and c["method"] == "POST"]

# ---------------------------------------------------------------- streams (decoded)
assert os.path.exists(os.path.join(DER, "cam_index.json")), "streams/derived/cam_index.json missing: decode_streams.py not finished"
pose = []
with open(os.path.join(DER, "base_20hz.csv")) as f:
    rows_pose = list(csv.DictReader(f))
last = None
for i, r in enumerate(rows_pose):   # keep a point when the base moved 2 mm / 0.004 rad, or every 5 s
    t, x, y, th = float(r["t_wall"]), float(r["x"]), float(r["y"]), float(r["theta"])
    if (last is None or i == len(rows_pose) - 1 or math.hypot(x - last[1], y - last[2]) > 0.002
            or abs(th - last[3]) > 0.004 or t - last[0] > 5):
        last = (t, x, y, th)
        pose.append([round(t, 2), round(x, 4), round(y, 4), round(th, 4)])
travel = sum(math.hypot(pose[i][1] - pose[i - 1][1], pose[i][2] - pose[i - 1][2]) for i in range(1, len(pose)))
n_base_rows = len(rows_pose)
del rows_pose


def fnum(s):
    v = float(s)
    return None if math.isnan(v) else v


# arm: 4 Hz bins. z / commanded z / gap: bin mean; tracking error and force: bin max (so short peaks stay visible)
arm_cols = ("t", "z", "cz", "e", "gap", "f", "en")
arm = {k: [] for k in arm_cols}
n_arm_rows, arm_t0, arm_t1 = 0, None, None
with open(os.path.join(DER, "arm_50hz.csv")) as f:
    rd = csv.reader(f)
    hdr = next(rd)
    ix = {k: hdr.index(k) for k in ("t_wall", "enabled", "z", "cmd_z", "err_pos", "g_gap", "g_force")}
    cur_bin, acc = None, None

    def flush_bin():
        if not acc: return
        def mean(v):
            v = [x for x in v if x is not None]
            return sum(v) / len(v) if v else None
        def mx(v):
            v = [x for x in v if x is not None]
            return max(v) if v else None
        z, cz, e, gp, fo = mean(acc["z"]), mean(acc["cz"]), mx(acc["e"]), mean(acc["gap"]), mx(acc["f"])
        arm["t"].append(round(mean(acc["t"]), 2))
        arm["z"].append(None if z is None else round(z, 4))
        arm["cz"].append(None if cz is None else round(cz, 4))
        arm["e"].append(None if e is None else round(e * 1000, 2))
        arm["gap"].append(None if gp is None else round(gp * 1000, 2))     # g_gap is in metres
        arm["f"].append(None if fo is None else round(fo, 1))
        arm["en"].append(1 if max(acc["en"]) > 0.5 else 0)

    for row in rd:
        t = float(row[ix["t_wall"]])
        n_arm_rows += 1
        arm_t0 = t if arm_t0 is None else arm_t0
        arm_t1 = t
        b = int(t // ARM_BIN)
        if b != cur_bin:
            flush_bin()
            cur_bin, acc = b, {"t": [], "z": [], "cz": [], "e": [], "gap": [], "f": [], "en": []}
        acc["t"].append(t); acc["z"].append(fnum(row[ix["z"]])); acc["cz"].append(fnum(row[ix["cmd_z"]]))
        acc["e"].append(fnum(row[ix["err_pos"]])); acc["gap"].append(fnum(row[ix["g_gap"]]))
        acc["f"].append(fnum(row[ix["g_force"]])); acc["en"].append(float(row[ix["enabled"]]))
    flush_bin()
arm_rate = (n_arm_rows - 1) / (arm_t1 - arm_t0)

gev = []
with open(os.path.join(DER, "gripper_events.csv")) as f:
    for r in csv.DictReader(f):
        gev.append({"t": float(r["t_wall"]), "goal": float(r["gap_goal_mm"]), "gap2": float(r["gap_2s_later_mm"]),
                    "f2": float(r["force_2s_later_n"])})

cam_index = json.load(open(os.path.join(DER, "cam_index.json")))
cam = [[c["n"], round(c["t_wall"], 3)] for c in cam_index]
assert [c[0] for c in cam] == list(range(len(cam))), "cam_index frames are not 0..N-1 (video time = n / 10 s assumes that)"
thumb_path = lambda n: os.path.join(DER, "cam_thumbs", f"{n:06d}.jpg")
video_path = os.path.join(DER, "review_10x.mp4")
video_bytes = os.path.getsize(video_path)

# ---------------------------------------------------------------- transcript
rows = [json.loads(l) for l in open(P("claude_transcript.jsonl"))]
results = {}
for r in rows:
    if r.get("type") == "user" and isinstance(r["message"]["content"], list):
        for b in r["message"]["content"]:
            if b.get("type") == "tool_result":
                results[b["tool_use_id"]] = (b, r["timestamp"])

cmdno, seen = {}, set()
for r in rows:
    m = r.get("message")
    if isinstance(m, dict) and isinstance(m.get("content"), list):
        for b in m["content"]:
            if b.get("type") == "tool_use" and b.get("name") in ("Bash", "Write", "Edit") and b["id"] not in seen:
                seen.add(b["id"]); cmdno[b["id"]] = len(seen)

EP = "/Users/aves/Documents/code/robot_utils/docs/episodes/2026-11-10-trash-can/"
events = []  # (t, kind, html)
ticks = []   # (t, kind)
nimg = nerr = 0
flags = {"error": 0, "denied": 0}


def res_text(content):
    if isinstance(content, str): return content, []
    txt, ims = [], []
    for x in content or []:
        if x.get("type") == "text": txt.append(x["text"])
        elif x.get("type") == "image": ims.append(x)
    return "\n".join(txt), ims


def result_block(tid):
    if tid not in results:
        return "<div class='lab'>no tool result recorded</div>", "", [], None
    b, ts = results[tid]
    txt, ims = res_text(b.get("content"))
    flag = ""
    if "Permission for this action was denied" in txt: flag = "denied"
    elif b.get("is_error"): flag = "error"
    h = ""
    if txt.strip() or not ims:
        nl = txt.count("\n") + 1 if txt else 0
        first = next((l for l in txt.split("\n") if l.strip()), "(empty)")
        if len(first) > 110: first = first[:110] + "…"
        badge = f"<span class='flag {flag}'>{flag}</span>" if flag else ""
        op = " open" if flag else ""
        h += (f"<details class='res'{op}><summary>{badge}<span class='rl'>result · {nl} line{'s' if nl != 1 else ''} · {clock(iso2t(ts))}</span>"
              f"<span class='rp'>{esc(first)}</span></summary><pre>{esc(txt)}</pre></details>")
    return h, flag, ims, ts


def tool_html(b, ts):
    global nimg, nerr
    name, inp, tid = b["name"], b["input"], b["id"]
    n = cmdno.get(tid)
    rh, flag, ims, rts = result_block(tid)
    rts = rts or ts
    if flag:
        nerr += 1; flags[flag] += 1
    cn = f"<a class='cn' href='#cmd-{n}' title='verbatim entry #{n} in tools/commands.md'>#{n}</a>" if n else ""
    short = name
    desc = ""
    body = ""
    if name == "Bash":
        desc = inp.get("description", "")
        bg = " <span class='lab'>(run_in_background)</span>" if inp.get("run_in_background") else ""
        body = f"<pre class='cmd'>{esc(inp['command'])}</pre>{bg}"
    elif name == "Read":
        fp = inp["file_path"]
        desc = fp.replace(EP, "")
        extra = {k: v for k, v in inp.items() if k != "file_path"}
        if extra: body += f"<pre class='cmd'>{esc(json.dumps(extra))}</pre>"
    elif name == "Write":
        desc = inp["file_path"].replace(EP, "")
        body = f"<div class='lab'>file content</div><pre class='cmd'>{esc(inp['content'])}</pre>"
    elif name == "Edit":
        desc = inp["file_path"].replace(EP, "")
        ra = " · replace_all" if inp.get("replace_all") else ""
        body = (f"<div class='lab'>old_string{ra}</div><pre class='cmd del'>{esc(inp['old_string'])}</pre>"
                f"<div class='lab'>new_string</div><pre class='cmd add'>{esc(inp['new_string'])}</pre>")
    elif name == "SubagentHandback" and set(inp) == {"message"}:
        desc = "report handed back to the parent session"
        body = (f"<div class='lab'>message (the tool input, rendered as Markdown)</div>"
                f"<div class='hb body'>{md(inp['message'])}</div>")
    else:
        body = f"<pre class='cmd'>{esc(json.dumps(inp, indent=1, ensure_ascii=False))}</pre>"
    imh = ""
    for x in ims:
        nimg += 1
        f = os.path.basename(inp.get("file_path", "")) if name == "Read" else None
        if name == "Read":
            src = "img/" + f if f in imgs else None
        else:
            src = f"data:{x['source']['media_type']};base64,{x['source']['data']}"
        if src:
            cap = f"img/{f}" if name == "Read" else "screenshot returned by the tool (embedded; not saved in img/)"
            imh += f"<figure><img loading='lazy' src='{src}' alt='{esc(cap)}'><figcaption>{esc(cap)}</figcaption></figure>"
            ticks.append((iso2t(rts), "img"))
        else:
            imh += f"<div class='lab'>image result: {esc(inp.get('file_path'))} (file not found in img/)</div>"
    if flag: ticks.append((iso2t(rts), "err"))
    cls = f" {flag}" if flag else ""
    head = (f"<div class='th'><span class='tn'>{esc(short)}</span><span class='desc'>{esc(desc)}</span>{cn}"
            f"<span class='t'>{clock(iso2t(ts))}</span></div>")
    return f"<div class='tool{cls}'>{head}{body}{imh}{rh}</div>"


def user_html(text, ts, note=""):
    return (f"<div class='msg user'><div class='who'>User <span class='t'>{clock(iso2t(ts))}</span>{note}</div>"
            f"<div class='body'>{md(text)}</div></div>")


# ---- scope: the replay runs from the brief (row 0) through the stop ("[Request interrupted by user]").
# Everything after the stop is the post-experiment interview; it is replaced by one visible marker.
# Nothing inside the kept range is altered. The full record stays in claude_transcript.jsonl.
def _stop_row():
    for i, r in enumerate(rows):
        if r.get("type") == "user" and isinstance(r["message"]["content"], list):
            for b in r["message"]["content"]:
                if b.get("type") == "text" and b["text"].startswith("[Request interrupted by user"):
                    return i
    raise SystemExit("scope anchor not found: the stop")


STOP_ROW = _stop_row()
n_omit = 0
omit_at = None

for ri, r in enumerate(rows):
    ty = r.get("type")
    ts = r.get("timestamp")
    if ri > STOP_ROW:
        if ty in ("user", "assistant") or (ty == "attachment" and r["attachment"].get("type") == "queued_command"):
            if omit_at is None:
                omit_at = len(events); events.append(None)
            n_omit += 1
        continue
    if ty == "user":
        c = r["message"]["content"]
        if isinstance(c, str):
            if c.lstrip().startswith("<system-reminder>"):
                events.append((iso2t(ts), "sys", f"<details class='sys'><summary><span class='t'>{clock(iso2t(ts))}</span> system reminder (harness text in the user turn)</summary><pre>{esc(c)}</pre></details>"))
            else:
                note = " <span class='lab'>the brief, from the parent session</span>" if ri == 0 else " <span class='lab'>from the parent session (coordinator)</span>"
                events.append((iso2t(ts), "user", user_html(c, ts, note)))
                ticks.append((iso2t(ts), "user"))
        else:
            for b in c:
                if b.get("type") == "text":
                    if ri == STOP_ROW:
                        events.append((iso2t(ts), "sys", "<div class='sys omit'>Annotation, not part of the transcript: the operator&rsquo;s &ldquo;terminate the session&rdquo; went to the parent session, which stopped this subagent. The next entry is that stop, as recorded. See README, &ldquo;Termination&rdquo;.</div>"))
                        ticks.append((iso2t(ts), "user"))
                    events.append((iso2t(ts), "sys", f"<div class='sys stop'><span class='t'>{clock(iso2t(ts))}</span> {esc(b['text'])}</div>"))
    elif ty == "assistant":
        for b in r["message"]["content"]:
            if b["type"] == "text":
                events.append((iso2t(ts), "asst", f"<div class='msg asst'><div class='who'>Claude <span class='t'>{clock(iso2t(ts))}</span></div><div class='body'>{md(b['text'])}</div></div>"))
            elif b["type"] == "thinking":
                t = b.get("thinking") or ""
                inner = f"<div class='body'>{md(t)}</div>" if t.strip() else ""
                lab = "thinking" if t.strip() else "thinking · text not stored in the transcript (signature only)"
                events.append((iso2t(ts), "think", f"<div class='think'><span class='t'>{clock(iso2t(ts))}</span> {lab}{inner}</div>"))
            elif b["type"] == "tool_use":
                events.append((iso2t(ts), "tool", tool_html(b, ts)))
    elif ty == "attachment" and r["attachment"].get("type") == "queued_command":
        a = r["attachment"]
        kind = (a.get("origin") or {}).get("kind")
        if kind in ("human", "coordinator"):
            who = "from the parent session (coordinator); " if kind == "coordinator" else ""
            events.append((iso2t(ts), "user", user_html(a["prompt"], ts, f" <span class='lab'>{who}sent while Claude was working (queued)</span>")))
            ticks.append((iso2t(ts), "user"))
        else:
            first = a["prompt"].strip().split("\n")
            summ = next((re.sub(r"<[^>]+>", "", l) for l in first if "<summary>" in l or "<status>" in l), "background task notification")
            events.append((iso2t(ts), "sys", f"<details class='sys'><summary><span class='t'>{clock(iso2t(ts))}</span> system · {esc(summ.strip())}</summary><pre>{esc(a['prompt'])}</pre></details>"))
    elif ty == "system" and r.get("subtype") == "api_error":
        e = r.get("error") or {}
        events.append((iso2t(ts), "sys", f"<div class='sys'><span class='t'>{clock(iso2t(ts))}</span> system · API error: {esc(e.get('formatted') or e.get('message'))} (retried)</div>"))

if omit_at is not None:
    t_mark = max(e[0] for e in events if e)
    events[omit_at] = (t_mark, "sys", f"<div class='sys omit'>⋯ {n_omit} transcript entr{'y' if n_omit == 1 else 'ies'} omitted from this replay: "
                       f"the post-experiment interview (questions from the parent session, the subagent&rsquo;s answers). "
                       f"It is on the <a href='#tab-interview'>Interview</a> tab (<code>INTERVIEW.md</code>); the full record is in <code>claude_transcript.jsonl</code>.</div>")

tm = 0
EV = []
parts = []
for i, (t, k, h) in enumerate(events):
    tm = max(tm, t)
    EV.append(round(tm, 3))
    parts.append(f"<div class='ev {k}' data-i='{i}'>{h}</div>")
transcript_html = "\n".join(parts)

T0 = EV[0]
T1 = max(EV[-1], calls[-1]["t"])

# phases, derived from call and transcript timing (see README "What happened")
ct = lambda pred: next(c["t"] for c in calls if pred(c))
handbacks = [iso2t(r["timestamp"]) for i, r in enumerate(rows) if i < STOP_ROW and r.get("type") == "assistant"
             for b in r["message"]["content"] if b["type"] == "tool_use" and b["name"] == "SubagentHandback"]
resumes = [iso2t(rows[i]["timestamp"]) for i in range(STOP_ROW) if rows[i].get("type") == "user"
           and isinstance(rows[i]["message"]["content"], str) and rows[i]["message"]["content"].startswith("The coordinator sent a message")]
t_stop = iso2t(rows[STOP_ROW]["timestamp"])
t_arm_on = ct(lambda c: c["path"] == "enable" and c["node"] == "arm")
t_nav_on = ct(lambda c: c["path"] == "enable" and c["node"] == "nav")
t_g141 = next(g["t"] for g in goals if g["id"] == 141)
assert len(handbacks) == 2 and len(resumes) == 2, (handbacks, resumes)
phases = [
    ["setup", T0, t_arm_on],
    ["arm + grasp", t_arm_on, t_nav_on],
    ["retreat + scan", t_nav_on, t_g141],
    ["blocked by reflex", t_g141, handbacks[0]],
    ["pause", handbacks[0], resumes[0]],
    ["creep (option a)", resumes[0], handbacks[1]],
    ["pause", handbacks[1], resumes[1]],
    ["release on floor", resumes[1], t_stop],
    ["shutdown", t_stop, T1],
]

# ---------------------------------------------------------------- tools tab
cmd_src = open(P("tools", "commands.md")).read()
heads = list(re.finditer(r"^## #(\d+) (Bash|Write|Edit): (.*)$", cmd_src, re.M))
k = 1
filt = []
for h in heads:  # keep only the sequential headers (a header-like line inside a code block would break the order)
    if int(h.group(1)) == k:
        filt.append(h); k += 1
id2ev = {}
for i, (t, kk, h) in enumerate(events):
    m = re.search(r"href='#cmd-(\d+)'", h)
    if m: id2ev[int(m.group(1))] = i
cmd_html = []
cmd_flags = {"error": 0, "denied": 0}
for j, h in enumerate(filt):
    end = filt[j + 1].start() if j + 1 < len(filt) else len(cmd_src)
    chunk = cmd_src[h.end():end].strip("\n")
    meta, _, rest = chunk.partition("\n\n")
    fm = re.match(r"^(`{3,})[^\n]*\n", rest)
    body = rest
    if fm:
        body = rest[fm.end():]
        body = body[: body.rstrip().rfind("\n" + fm.group(1))] if ("\n" + fm.group(1)) in body else body
    n = int(h.group(1))
    st = meta.split("result: ")[-1].strip()
    if st in cmd_flags: cmd_flags[st] += 1
    flag = f" <span class='flag {st}'>{st}</span>" if st in ("error", "denied") else ""
    back = f" <a class='back' href='#ev-{id2ev[n]}'>in transcript</a>" if n in id2ev else ""
    cmd_html.append(f"<details class='cmdent' id='cmd-{n}'><summary><span class='cnum'>#{n}</span> <span class='tn'>{h.group(2)}</span> {esc(h.group(3))}{flag}</summary>"
                    f"<div class='lab'>{esc(meta)}{back}</div><pre>{esc(body)}</pre></details>")


def link_cmds(s):
    s = inline(s)
    s = s.replace('href="tools/commands.md"', 'href="#commands"')
    return re.sub(r"(?<![\w&/])#(\d+)(?:(–|-)(\d+))?",
                  lambda m: f"<a class='cref' href='#cmd-{m.group(1)}'>#{m.group(1)}</a>" + (f"{m.group(2)}<a class='cref' href='#cmd-{m.group(3)}'>{m.group(3)}</a>" if m.group(3) else ""), s)


def doc_links(s):
    return (s.replace('href="INTERVIEW.md"', 'href="#tab-interview"').replace('href="TOOLS.md"', 'href="#tab-tools"')
            .replace('href="README.md"', 'href="#tab-readme"'))


tools_html = doc_links(md(open(P("TOOLS.md")).read(), inl=link_cmds, details=True))
tools_html = re.sub(r"(<p>See <code>img/([\w.-]+)</code>.*?</p>)",
                    lambda m: m.group(1) + (f"<figure><img loading='lazy' src='img/{m.group(2)}' alt='img/{m.group(2)}'><figcaption>img/{m.group(2)}</figcaption></figure>" if m.group(2) in imgs else ""), tools_html)
readme_html = doc_links(md(open(P("README.md")).read(), details=True))
interview_html = doc_links(md(open(P("INTERVIEW.md")).read(), details=True))

# ---------------------------------------------------------------- header numbers (all derived)
nlooks = len(looks); nq = sum(1 for c in calls if c["path"].startswith("query"))
robot_min = (calls[-1]["t"] - calls[0]["t"]) / 60
gres = {}
for g in goals: gres[g["res"] or "no result"] = gres.get(g["res"] or "no result", 0) + 1
goal_txt = ", ".join(f"{v} {k}" for k, v in sorted(gres.items(), key=lambda kv: -kv[1]))
n_stop_reflex = sum(1 for g in goals if g["res"] == "stopped")
cam_min = (cam[-1][1] - cam[0][1]) / 60
t_close = next(g["t"] for g in gev if g["goal"] == 0)
held_min = (next(g["t"] for g in gev if g["goal"] > 0 and g["t"] > t_close) - t_close) / 60

TEMPLATE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Foam Block to Trash Can</title><meta name="description" content="Episode replay, 2026-11-10: Claude drove the swerve base and arm to pick up a foam block and drop it into a trash can; it failed. Transcript synced with the recorded trajectory, camera, video, arm telemetry and robot calls.">
<style>
:root{color-scheme:light;--bg:#f6f5f2;--card:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#7a7974;--line:#dedcd6;--grid:#ebe9e4;
--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--s4:#eda100;--s7:#6250d6;--s8:#e34948;--code:#efede8;--user:#eaf1fb;--think:#f3f0fa;--acc:#2a78d6}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--bg:#121211;--card:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;--line:#34332f;--grid:#2a2926;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s7:#9085e9;--s8:#e66767;--code:#24231f;--user:#1b2533;--think:#221f2c;--acc:#3987e5}}
:root[data-theme="dark"]{color-scheme:dark;--bg:#121211;--card:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#8f8e86;--line:#34332f;--grid:#2a2926;
--s1:#3987e5;--s2:#d95926;--s3:#199e70;--s4:#c98500;--s7:#9085e9;--s8:#e66767;--code:#24231f;--user:#1b2533;--think:#221f2c;--acc:#3987e5}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wrap{max-width:1480px;margin:0 auto;padding:0 16px}
header.top{padding:24px 0 6px}
h1{font-size:1.9rem;line-height:1.2;margin:.2em 0 .1em}h2{font-size:1.25rem;margin:1.6em 0 .5em}h3{font-size:1.05rem;margin:1.2em 0 .4em}h4{font-size:.98rem;margin:1em 0 .3em}
.sub{color:var(--ink2);margin:0 0 1em}.lede{max-width:880px}
.outc{display:inline-block;font-size:.78rem;font-weight:650;letter-spacing:.04em;text-transform:uppercase;color:var(--s8);border:1px solid var(--s8);border-radius:5px;padding:0 6px;vertical-align:2px}
a{color:var(--acc)}code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.84em}
code{background:var(--code);padding:.05em .3em;border-radius:4px;overflow-wrap:anywhere}
pre{background:var(--code);padding:8px 10px;border-radius:6px;overflow:auto;white-space:pre-wrap;word-break:break-word;max-height:420px;margin:.3em 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:1em 0}
.tile{border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.tile .n{font-size:1.35rem;font-weight:650;line-height:1.15}.tile .l{color:var(--ink2);font-size:.84rem}
.tile.bad .n{color:var(--s8)}
.summary{max-width:880px;margin:0;padding-left:1.3em}.summary li{margin:.25em 0}
.note{font-size:.86rem;color:var(--ink2);max-width:880px;margin:.6em 0 0}
.tabs{display:flex;gap:4px;border-bottom:1px solid var(--line);margin-top:18px;overflow-x:auto;scrollbar-width:none}
.tabs button{font:inherit;font-size:.92rem;background:none;border:1px solid transparent;border-bottom:none;border-radius:8px 8px 0 0;padding:6px 14px;color:var(--ink2);cursor:pointer;margin-bottom:-1px;white-space:nowrap}
.tabs button[aria-selected="true"]{color:var(--ink);border-color:var(--line);background:var(--bg)}
.tab[hidden]{display:none}
/* controls */
.ctrl{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:8px 0 6px}
.crow{display:flex;align-items:center;gap:10px}
.btn{font:inherit;font-size:.86rem;background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:7px;padding:4px 10px;cursor:pointer;white-space:nowrap}
.btn:hover{border-color:var(--muted)}select.btn{padding:4px 6px}
.clock{font-variant-numeric:tabular-nums;font-size:.86rem;color:var(--ink2);white-space:nowrap;min-width:12.5em;text-align:right}
.scrub{position:relative;flex:1;min-width:0;height:34px}
.scrub input{position:absolute;left:0;right:0;bottom:-2px;width:100%;margin:0;accent-color:var(--acc)}
.bands{position:absolute;left:0;right:0;top:0;height:14px}
.band{position:absolute;top:0;height:14px;border-left:1px solid var(--line);font-size:.68rem;color:var(--muted);padding-left:3px;overflow:hidden;white-space:nowrap;line-height:14px}
.tks{position:absolute;left:0;right:0;top:15px;height:7px}
.tk{position:absolute;top:0;width:1px;height:7px;background:var(--muted);opacity:.5}.tk.user{background:var(--acc);opacity:1;height:7px;width:2px}.tk.err{background:var(--s8);opacity:1}
.legend{display:flex;gap:12px;flex-wrap:wrap;font-size:.74rem;color:var(--muted);margin-top:2px}
.legend i{display:inline-block;width:10px;height:2px;vertical-align:3px;margin-right:4px;background:var(--c)}
/* panes */
.panes{display:grid;grid-template-columns:minmax(0,1fr) minmax(400px,.8fr);gap:16px;height:calc(100vh - 78px)}
.tl{overflow-y:auto;padding:6px 12px 40vh 0;border-right:1px solid var(--line);scrollbar-gutter:stable}
.rv{overflow-y:auto;padding:10px 0 20px;display:flex;flex-direction:column;gap:12px;min-height:0}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.card h3{margin:0 0 4px;font-size:.88rem;font-weight:600;color:var(--ink2);display:flex;justify-content:space-between;gap:8px;align-items:baseline;flex-wrap:wrap}
.card h3 .muted{font-weight:400}
.muted{color:var(--muted);font-size:.82em}
.row2{display:grid;grid-template-columns:1fr 1fr;gap:12px}
/* transcript */
.ev{position:relative;padding-left:14px;border-left:2px solid var(--line);scroll-margin-top:20px}
.ev.now{border-left-color:var(--acc)}
.ev .t{font-weight:400;color:var(--muted);font-size:.78rem;font-variant-numeric:tabular-nums;cursor:pointer}
.msg{margin:0;padding:10px 0}.msg .who{font-size:.78rem;color:var(--ink2);font-weight:600;margin-bottom:2px}
.msg .who .lab{font-weight:400;display:inline}
.msg .body{overflow-wrap:anywhere}.msg .body p{margin:.3em 0}.msg ul,.msg ol{margin:.3em 0;padding-left:1.3em}
.msg.user .body{background:var(--user);padding:8px 12px;border-radius:8px}
.hb{border:1px solid var(--line);border-radius:8px;padding:6px 12px;margin:4px 0;overflow-wrap:anywhere;font-size:.94rem}.hb p{margin:.3em 0}.hb ul,.hb ol{margin:.3em 0;padding-left:1.3em}
.think{font-size:.78rem;color:var(--muted);font-style:italic;padding:3px 0}
.sys{font-size:.8rem;color:var(--muted);padding:4px 0}.sys summary{cursor:pointer}.sys.omit{border:1px dashed var(--line);border-radius:6px;padding:8px 10px;margin:6px 0}
.sys.stop{color:var(--s8);font-weight:600}
.tool{padding:6px 0 8px}
.th{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;font-size:.86rem}
.th .tn{font-weight:600}.th .desc{color:var(--ink2);flex:1;min-width:0;overflow-wrap:anywhere}
.th .t{margin-left:auto}
a.cn{font-size:.76rem;color:var(--muted);text-decoration:none;border:1px solid var(--line);border-radius:5px;padding:0 5px}a.cn:hover{color:var(--acc);border-color:var(--acc)}
pre.cmd{font-size:.78em;max-height:320px}
pre.del{border-left:3px solid var(--s8)}pre.add{border-left:3px solid var(--s3)}
.lab{font-size:.74rem;color:var(--muted);margin-top:4px}
details.res{margin-top:3px}
details.res summary{cursor:pointer;font-size:.78rem;color:var(--muted);display:flex;gap:8px;align-items:baseline;list-style:none;min-width:0}
details.res summary::before{content:"\25B8";font-size:.7rem}details.res[open] summary::before{content:"\25BE"}
details.res summary::-webkit-details-marker{display:none}
.rl{white-space:nowrap}.rp{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:.95em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0;flex:1;opacity:.85}
details.res pre{font-size:.76em}
.flag{font-size:.7rem;font-weight:600;border:1px solid var(--s8);color:var(--s8);border-radius:5px;padding:0 5px;text-transform:uppercase;letter-spacing:.03em}
.flag.denied{border-color:var(--s4);color:var(--s4)}
.ev .tool.error details.res pre{border-left:3px solid var(--s8)}
.ev .tool.denied details.res pre{border-left:3px solid var(--s4)}
figure{margin:6px 0}figure img{display:block;max-width:min(100%,560px);height:auto;border-radius:6px;border:1px solid var(--line);cursor:zoom-in}
figcaption{color:var(--muted);font-size:.76rem;margin-top:2px}
/* right pane */
svg{display:block;width:100%;height:auto}
.map .gl{stroke:var(--grid);stroke-width:.004}.map .ax{fill:var(--muted);font-size:.032px}
.map .all{fill:none;stroke:var(--line);stroke-width:.006}.map .trail{fill:none;stroke:var(--s1);stroke-width:.007;stroke-linejoin:round}
.map .fp{fill:none;stroke:var(--ink2);stroke-width:.005}.map .hd{stroke:var(--s1);stroke-width:.008}
.map .fov{fill:var(--s1);fill-opacity:.06;stroke:none}
.map .snap{fill:var(--card);stroke:var(--muted);stroke-width:.004;cursor:pointer}.map .snap.done{stroke:var(--ink2)}.map .snap.cur{stroke:var(--s2);stroke-width:.007}
.map .gx{stroke:var(--muted);stroke-width:.005}.map .gx.cur{stroke:var(--s2);stroke-width:.008}
.map .gline{stroke:var(--s2);stroke-width:.004;stroke-dasharray:.012 .01;opacity:0}.map .gline.cur{opacity:.9}
.mapkey{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.74rem;color:var(--muted);margin-top:4px}
.mapkey span::before{content:"";display:inline-block;width:12px;height:0;border-top:2px solid var(--c);margin-right:5px;vertical-align:3px}
.mapkey span.dash::before{border-top-style:dashed}.mapkey span.pt::before{width:7px;height:7px;border:0;border-radius:50%;background:var(--c);vertical-align:0}
.mapkey span.box::before{width:12px;height:8px;border:0;background:var(--c);vertical-align:-1px}
.cam img{display:block;width:100%;height:auto;border-radius:6px;border:1px solid var(--line);cursor:zoom-in;background:var(--code);aspect-ratio:4/3;object-fit:contain}
.seg{display:inline-flex;border:1px solid var(--line);border-radius:6px;overflow:hidden}
.seg button{font:inherit;font-size:.72rem;background:none;border:0;color:var(--muted);padding:1px 7px;cursor:pointer}
.seg button[aria-pressed="true"]{color:var(--ink);background:var(--code)}.seg .sm{display:none}
.capt{font-size:.76rem;color:var(--ink2);margin-top:4px;min-height:2.4em}
.vid video{display:block;width:100%;height:auto;aspect-ratio:1760/550;background:#121211;border-radius:6px;border:1px solid var(--line)}
.vnote{font-size:.78rem;color:var(--ink2);border:1px dashed var(--line);border-radius:6px;padding:8px 10px;margin-top:6px}
.vid .lnk{font:inherit;font-size:.74rem;background:none;border:0;color:var(--acc);cursor:pointer;padding:0;text-decoration:underline}
.plot .gl{stroke:var(--grid)}.plot .ax{fill:var(--muted);font-size:10px}.plot .zl{stroke:var(--line)}.plot .pl{fill:var(--ink2);font-size:10px;font-weight:600}
.plot .off{fill:var(--grid);opacity:.7}
.plot .cz{fill:none;stroke:var(--muted);stroke-width:1.2;stroke-dasharray:3 3}.plot .mz{fill:none;stroke:var(--s1);stroke-width:1.5}
.plot .rg{fill:var(--card);stroke:var(--ink2);stroke-width:1.2}.plot .rm{fill:var(--s1);stroke:var(--card);stroke-width:1}
.plot .er{fill:none;stroke:var(--s2);stroke-width:1.3}.plot .re{fill:var(--s2);stroke:var(--card);stroke-width:1}
.plot .gp{fill:none;stroke:var(--s3);stroke-width:1.5}.plot .fo{fill:none;stroke:var(--s7);stroke-width:1.2}.plot .clip{fill:var(--s7)}
.plot .gev{stroke:var(--s3);stroke-width:1;stroke-dasharray:2 2}.plot .gevl{fill:var(--s3);font-size:9px}
.plot .cur{stroke:var(--ink);stroke-width:1;opacity:.55}
.plot{position:relative}.tip{position:absolute;pointer-events:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:4px 8px;font-size:.74rem;color:var(--ink);box-shadow:0 2px 8px rgba(0,0,0,.15);white-space:nowrap;display:none;z-index:3}
.log{flex:1;min-height:220px;display:flex;flex-direction:column}
.logl{overflow-y:auto;flex:1;min-height:200px;max-height:none;border-top:1px solid var(--line);margin-top:4px;font-size:.76rem}
.lr{display:grid;grid-template-columns:4.6em 2.6em minmax(0,1fr);gap:6px;padding:3px 4px;border-bottom:1px solid var(--grid);cursor:pointer;align-items:baseline}
.lr:hover{background:var(--code)}.lr.fut{opacity:.42}.lr.cur{box-shadow:inset 3px 0 0 var(--acc);background:var(--code)}
.lr .tt{color:var(--muted);font-variant-numeric:tabular-nums}.lr .nd{color:var(--ink2)}.lr .nd.arm{color:var(--s7)}
.lr .pp{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}.lr .ss{color:var(--ink2);font-family:inherit}
.lr .bad{color:var(--s8);font-weight:600}
/* modal */
.ov{position:fixed;inset:0;background:rgba(0,0,0,.55);display:none;align-items:center;justify-content:center;z-index:20;padding:16px}
.ov.on{display:flex}.ovb{background:var(--card);border:1px solid var(--line);border-radius:10px;max-width:min(980px,100%);max-height:100%;overflow:auto;padding:12px 14px}
.ovb img{max-width:100%;height:auto;display:block;margin:6px 0;border-radius:6px}
.ovb pre{max-height:none}
.ovh{display:flex;justify-content:space-between;gap:10px;font-size:.84rem;color:var(--ink2)}
/* docs */
.doc{max-width:960px;padding:8px 0 64px}
.doc table{border-collapse:collapse;font-size:.86rem;width:100%}.doc th,.doc td{border-bottom:1px solid var(--line);padding:5px 8px;text-align:left;vertical-align:top}.doc th{color:var(--ink2);font-weight:600}
.doc details.mdd{border:1px solid var(--line);border-radius:8px;padding:6px 12px;margin:.6em 0}.doc details.mdd summary{cursor:pointer;color:var(--ink2)}
.tw{overflow-x:auto;max-width:100%}
a.cref{text-decoration:none;border-bottom:1px dotted var(--acc)}
.cmdent{border-bottom:1px solid var(--line);padding:4px 0}.cmdent summary{cursor:pointer;font-size:.88rem}.cmdent .cnum{font-variant-numeric:tabular-nums;color:var(--muted);display:inline-block;min-width:2.6em}
.cmdent .tn{font-weight:600;margin-right:4px}.cmdent:target,.cmdent.hl{background:var(--code);border-radius:6px}
.back{margin-left:8px}
#vtog{display:none}
@media (max-width:900px){
 .panes{display:block;height:auto}
 .tl{overflow:visible;border-right:0;padding:6px 0 30vh}
 .rv{overflow:visible;padding:10px 0 4px}
 .logl{max-height:240px}
 .clock{min-width:0}
 .rv{display:flex}.panes{display:flex;flex-direction:column}.rv{order:-1}
 #mini .row2{grid-template-columns:1fr 1.33fr;gap:8px;margin-top:6px}
 #mini .card{padding:6px 8px}#mini .card h3{font-size:.74rem;margin-bottom:2px}#mini .mapkey,#mini .card>.muted{display:none}
 #mini .capt{font-size:.68rem;min-height:0;max-height:2.6em;overflow:hidden}#mini #poseTxt{display:none}
 #mini.off{display:none}#vtog{display:inline-block}
 #mini .seg .lg{display:none}#mini .seg .sm{display:inline}
}
@media (max-width:560px){
 .band span{display:none}.row2{grid-template-columns:1fr}.lr{grid-template-columns:4.4em 2.4em minmax(0,1fr)}
 .crow{flex-wrap:wrap}.scrub{order:5;flex-basis:100%}.clock{margin-left:auto}
 h1{font-size:1.55rem}
 #mini .seg button{padding:1px 4px}
}
</style></head><body>
<div class="wrap">
<header class="top">
<p class="sub" style="margin:0">Episode replay &middot; botcore swerve base + arm &middot; 2026-11-10 __START__&ndash;__END__ EST</p>
<h1>Foam block into the trash can</h1>
<p class="sub lede"><strong>Task</strong> (from the brief): &ldquo;pick up the white foam block, then drop it into the trash can, which is somewhere to the LEFT of the robot.&rdquo; <strong>Outcome:</strong> <span class="outc">failed</span> The block was picked up and carried to within ~1.15&nbsp;m of an open trash can. The subagent judged the drop unreachable from untested estimates, then released the block over the floor instead of refusing. The block hung on the finger and fell into the camera&rsquo;s blind zone. It never reached the can, and the operator terminated the run.</p>
<ol class="summary">
<li><strong>Grasp.</strong> The arm had sagged while floating between runs, so the TCP was pulled back and raised before going home. One finger went through the block&rsquo;s hole and the jaws closed to 5.6&nbsp;mm at 21.8&nbsp;N, after approach steps of 1.5&nbsp;cm with a look and a depth check after each.</li>
<li><strong>Search.</strong> The robot retreated along the previous run&rsquo;s path and turned left in 45&deg; steps. It found a black trash can about 3.4&nbsp;m away.</li>
<li><strong>Approach.</strong> The stop reflex braked on the held block at the start of every forward leg. Lowering the block out of the camera&rsquo;s view was denied by the permission classifier (<a class="cref" href="#cmd-70">#70</a>). After a pause, the operator approved only re-issuing goals after self-triggered stops. <code>creep.py</code> did that and brought the base to ~1.15&nbsp;m from the can.</li>
<li><strong>Stop and release.</strong> It judged the drop unreachable and paused again. After the operator&rsquo;s &ldquo;no hints&rdquo;, it opened the gripper over open floor, and the block hung on the inner finger. The operator&rsquo;s &ldquo;not allowed to litter&rdquo; reached it then. It re-closed the gripper, the block fell into the blind zone, and the operator terminated the run.</li>
</ol>
<p class="note"><a href="#tab-readme">README.md</a> records findings checked against the stream recordings: block motion during the grasp, the release and the fall.</p>
<div class="tiles">
 <div class="tile bad"><div class="n">failed</div><div class="l">block never reached the can; released over the floor</div></div>
 <div class="tile"><div class="n">__RMIN__ min</div><div class="l">robot session (first to last call)</div></div>
 <div class="tile"><div class="n">__NLOOK__ / __NQ__</div><div class="l">camera looks / 3D queries</div></div>
 <div class="tile"><div class="n">__NGOAL__</div><div class="l">base goals (ids __GID__): __GRES__</div></div>
 <div class="tile"><div class="n">__NSERVO__ / __NGRIP__</div><div class="l">arm servo results / gripper commands; block held __HELD__ min</div></div>
 <div class="tile"><div class="n">__TRAVEL__ m</div><div class="l">base path length (from the 20&nbsp;Hz estimator stream)</div></div>
 <div class="tile"><div class="n">__NCAM__</div><div class="l">camera frames recorded at 1&nbsp;Hz (__CAMMIN__ min); arm at __ARMHZ__&nbsp;Hz</div></div>
 <div class="tile"><div class="n">__NERR__ / __NDEN__</div><div class="l">commands with an error / denied (of __NCMD__)</div></div>
</div>
<nav class="tabs" role="tablist">
 <button role="tab" aria-selected="true" data-tab="replay">Replay</button>
 <button role="tab" aria-selected="false" data-tab="tools">Tools</button>
 <button role="tab" aria-selected="false" data-tab="readme">README</button>
 <button role="tab" aria-selected="false" data-tab="interview">Interview</button>
</nav>
</header>
</div>

<section class="tab" id="tab-replay">
<div class="ctrl"><div class="wrap">
 <div class="crow">
  <button class="btn" id="play" aria-label="Play">&#9654; Play</button>
  <select class="btn" id="speed" aria-label="Replay speed"><option value="10">10&times;</option><option value="30" selected>30&times;</option><option value="60">60&times;</option><option value="120">120&times;</option></select>
  <div class="scrub"><div class="bands" id="bands"></div><div class="tks" id="tks"></div><input type="range" id="rng" aria-label="Replay time" step="0.1"></div>
  <button class="btn" id="vtog" aria-pressed="true" title="show or hide the trajectory and camera strip">view</button>
  <div class="clock" id="clock"></div>
 </div>
 <div id="mini"></div>
 <div class="legend"><span style="--c:var(--acc)"><i></i>user message</span><span style="--c:var(--muted)"><i></i>image read</span><span style="--c:var(--s8)"><i></i>error / denied</span><span>phases derived from call and transcript timing &middot; playback skips idle gaps over 45&nbsp;s &middot; space = play/pause, &larr;/&rarr; = step</span></div>
</div></div>
<div class="wrap"><div class="panes">
 <div class="tl" id="tl">
__TRANSCRIPT__
 </div>
 <aside class="rv" id="rv">
  <div class="row2" id="row2">
   <div class="card"><h3>Base trajectory <span class="muted" id="poseTxt"></span></h3>
    <svg class="map" id="map" role="img" aria-label="Top-down base trajectory in the estimator world frame"></svg>
    <div class="mapkey"><span style="--c:var(--s1)">driven so far</span><span style="--c:var(--line)">whole run</span><span style="--c:var(--s2)">active goal</span></div>
    <div class="muted">estimator stream (20&nbsp;Hz, thinned to 2&nbsp;mm steps); world frame, <span id="gridTxt"></span> grid, x right / y up; square = 0.43&nbsp;m footprint, wedge = camera fov; circles = snapshots, &times; = goals</div>
   </div>
   <div class="card cam"><h3>Camera <span class="seg" id="seg"><button data-k="rec" aria-pressed="true" title="recorded colour frame nearest the cursor (1 Hz)"><span class="lg">recorded (1&nbsp;Hz)</span><span class="sm">rec</span></button><button data-k="img" aria-pressed="false" title="latest look snapshot">snapshot</button><button data-k="grid" aria-pressed="false">grid</button><button data-k="bev" aria-pressed="false">BEV</button></span></h3>
    <img id="camImg" alt="camera"><div class="capt" id="camCap"></div>
   </div>
  </div>
  <div class="card vid"><h3>Recording video <span class="muted">review_10x.mp4 &middot; colour | depth | top-down map &middot; 1 frame per recorded second, 10&times; speed</span></h3>
   __VIDEO__
   <div class="capt" id="vidCap"></div>
  </div>
  <div class="card"><h3>Arm telemetry <span class="seg" id="pseg"><button data-k="all" aria-pressed="true">whole run</button><button data-k="win" aria-pressed="false">&plusmn;1 min</button></span></h3>
   <div class="plot" id="plotWrap"><svg class="plot" id="plot" viewBox="0 0 520 300" role="img" aria-label="Arm TCP z measured and commanded, position tracking error, gripper gap and force over time"></svg><div class="tip" id="tip"></div></div>
   <div class="mapkey"><span style="--c:var(--s1)">measured z</span><span class="dash" style="--c:var(--muted)">commanded z</span><span class="pt" style="--c:var(--s1)">servo RESULT (hollow = goal)</span><span style="--c:var(--s2)">tracking error</span><span style="--c:var(--s3)">gripper gap</span><span style="--c:var(--s7)">gripper force</span><span class="dash" style="--c:var(--s3)">gripper goal change</span><span class="box" style="--c:var(--grid)">arm disabled</span></div>
   <div class="muted">arm stream, __ARMHZ__&nbsp;Hz binned to 4&nbsp;Hz: z and gap are bin means, tracking error (|position error|) and force are bin maxima. Force above 40&nbsp;N is clipped (&#9650;; peaks up to __FMAX__&nbsp;N at the start of each close). Arm base frame, m; gap converted from m to mm.</div>
  </div>
  <div class="card log"><h3>Robot calls <span class="muted" id="logN"></span></h3>
   __POSTNOTE__
   <div class="logl" id="log"></div>
  </div>
 </aside>
</div></div>
</section>

<section class="tab" id="tab-tools" hidden><div class="wrap"><div class="doc">
__TOOLS__
<h2 id="commands">tools/commands.md: every command and file write, verbatim</h2>
<p class="sub">Generated by <code>tools/extract_commands.py</code> from the transcript. Click an entry to expand it; &ldquo;in transcript&rdquo; jumps to the call in the replay.</p>
__CMDS__
</div></div></section>

<section class="tab" id="tab-readme" hidden><div class="wrap"><div class="doc">
__README__
</div></div></section>

<section class="tab" id="tab-interview" hidden><div class="wrap"><div class="doc">
__INTERVIEW__
</div></div></section>

<div class="ov" id="ov" role="dialog" aria-modal="true"><div class="ovb" id="ovb"></div></div>
<script type="application/json" id="data">__DATA__</script>
<script>
(function(){
const D=JSON.parse(document.getElementById('data').textContent);
const $=id=>document.getElementById(id);
const EV=D.ev,T0=D.t0,T1=D.t1;
const tl=$('tl'),rng=$('rng'),evEls=[...document.querySelectorAll('#tl .ev')];
evEls.forEach((e,i)=>e.id='ev-'+i);
const pad=n=>String(n).padStart(2,'0'),pad6=n=>String(n).padStart(6,'0');
const imgU=f=>(window.IMG&&window.IMG[f])||('img/'+f);
const thumbU=n=>(window.THUMB&&window.THUMB[n])||('streams/derived/cam_thumbs/'+pad6(n)+'.jpg');
const fullU=n=>D.camFull?'streams/cam/'+pad6(n)+'_color.jpg':thumbU(n);
function clk(t){const d=new Date((t+D.tz)*1000);return pad(d.getUTCHours())+':'+pad(d.getUTCMinutes())+':'+pad(d.getUTCSeconds())}
function el(t){const s=Math.max(0,Math.round(t-T0));return '+'+Math.floor(s/60)+':'+pad(s%60)}
function bs(arr,t,key){let lo=0,hi=arr.length-1,r=-1;while(lo<=hi){const m=(lo+hi)>>1;const v=key?key(arr[m]):arr[m];if(v<=t){r=m;lo=m+1}else hi=m-1}return r}
function esc(s){return String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
const X=t=>(t-T0)/(T1-T0)*100;
rng.min=T0;rng.max=T1;rng.value=T0;
$('bands').innerHTML=D.phases.map(p=>`<div class="band" style="left:${X(p[1])}%;width:${X(p[2])-X(p[1])}%" title="${p[0]} · ${clk(p[1])}–${clk(p[2])}"><span>${p[0]}</span></div>`).join('');
$('tks').innerHTML=D.ticks.map(k=>`<div class="tk ${k[1]}" style="left:${X(k[0])}%"></div>`).join('');

let T=T0,playing=false,lastF=0,progScroll=0,curEv=-1;
// ---------- map (world metres scaled by S so strokes and labels keep the reference page's proportions)
const map=$('map');let S=1;
(function(){
 let xs=D.pose.map(p=>p[1]),ys=D.pose.map(p=>p[2]);
 D.goals.forEach(g=>{xs.push(g.to[0]);ys.push(g.to[1])});
 const m=0.36;let x0=Math.min(...xs)-m,x1=Math.max(...xs)+m,y0=Math.min(...ys)-m,y1=Math.max(...ys)+m;
 const w=Math.max(x1-x0,y1-y0);const cx=(x0+x1)/2,cy=(y0+y1)/2;x0=cx-w/2;x1=cx+w/2;y0=cy-w/2;y1=cy+w/2;
 S=1.2/w;const q=v=>v*S;
 map.setAttribute('viewBox',`${q(x0)} ${q(-y1)} ${q(w)} ${q(w)}`);
 const gs=w>2.4?0.5:w>1.2?0.2:0.1,ls=gs*2;$('gridTxt').textContent=gs+' m';
 let s='';
 for(let g=Math.ceil(x0/gs)*gs;g<=x1;g+=gs)s+=`<line class="gl" x1="${q(g)}" x2="${q(g)}" y1="${q(-y1)}" y2="${q(-y0)}"/>`;
 for(let g=Math.ceil(y0/gs)*gs;g<=y1;g+=gs)s+=`<line class="gl" y1="${q(-g)}" y2="${q(-g)}" x1="${q(x0)}" x2="${q(x1)}"/>`;
 for(let g=Math.ceil(x0/ls)*ls;g<=x1-0.05/S;g+=ls)s+=`<text class="ax" x="${q(g)+0.006}" y="${q(-y0)-0.01}">${g.toFixed(1)}</text>`;
 for(let g=Math.ceil(y0/ls)*ls+ls;g<=y1-0.02/S;g+=ls)s+=`<text class="ax" x="${q(x0)+0.006}" y="${q(-g)-0.006}">${g.toFixed(1)}</text>`;
 s+=`<polyline class="all" points="${D.pose.map(p=>q(p[1])+','+q(-p[2])).join(' ')}"/>`;
 D.goals.forEach((g,i)=>{const a=q(g.to[0]),b=q(-g.to[1]),r=0.014;
  s+=`<line class="gline" id="gl${i}" x1="${q(g.from[0])}" y1="${q(-g.from[1])}" x2="${a}" y2="${b}"/>`;
  s+=`<g class="gx" id="gx${i}"><title>goal ${g.id} (${clk(g.t)}): ${g.res||''} ${g.why||''}\n${esc(g.c)}</title><line x1="${a-r}" y1="${b-r}" x2="${a+r}" y2="${b+r}"/><line x1="${a-r}" y1="${b+r}" x2="${a+r}" y2="${b-r}"/></g>`});
 s+=`<polyline class="trail" id="trail" points=""/>`;
 const fp=q(D.body.fp);
 s+=`<g id="bot"><path class="fov" id="fov"/><rect class="fp" x="${-fp/2}" y="${-fp/2}" width="${fp}" height="${fp}"/><line class="hd" x1="0" y1="0" x2="${fp/2+0.03}" y2="0"/></g>`;
 D.looks.forEach((l,i)=>{if(l.pose)s+=`<circle class="snap" id="sn${i}" cx="${q(l.pose[0])}" cy="${q(-l.pose[1])}" r="0.008" data-t="${l.t}"><title>${l.id} · ${clk(l.t)} · ${esc(l.c)}</title></circle>`});
 map.innerHTML=s;
 const hf=D.body.hfov/2*Math.PI/180,cy0=D.body.camyaw*Math.PI/180,L=0.32;
 $('fov').setAttribute('d',`M0 0 L${L*Math.cos(cy0+hf)} ${-L*Math.sin(cy0+hf)} L${L*Math.cos(cy0-hf)} ${-L*Math.sin(cy0-hf)}Z`);
 map.addEventListener('click',e=>{const t=e.target.getAttribute('data-t');if(t)setT(+t,'ui')});
})();
function poseAt(t){const P=D.pose;let i=bs(P,t,p=>p[0]);if(i<0)return P[0];if(i>=P.length-1)return P[P.length-1];
 const a=P[i],b=P[i+1],f=(t-a[0])/(b[0]-a[0]);let dth=b[3]-a[3];
 return [t,a[1]+(b[1]-a[1])*f,a[2]+(b[2]-a[2])*f,a[3]+dth*f]}
let lastTrail=-2;
function drawMap(t){const p=poseAt(t);
 $('bot').setAttribute('transform',`translate(${p[1]*S} ${-p[2]*S}) rotate(${-p[3]*180/Math.PI})`);
 const i=bs(D.pose,t,q=>q[0]);
 if(i!==lastTrail){lastTrail=i;$('trail').setAttribute('points',D.pose.slice(0,i+1).map(q=>q[1]*S+','+(-q[2]*S)).join(' ')+` ${p[1]*S},${-p[2]*S}`)}
 $('poseTxt').textContent=`x ${p[1].toFixed(3)} y ${p[2].toFixed(3)} θ ${p[3].toFixed(3)}`;
 const li=bs(D.looks,t,l=>l.t);
 D.looks.forEach((l,k)=>{const c=$('sn'+k);if(c)c.setAttribute('class','snap'+(k===li?' cur':k<li?' done':''))});
 const gi=bs(D.goals,t,g=>g.t);
 D.goals.forEach((g,k)=>{const on=k===gi&&t<=(g.end||g.t)+20;$('gx'+k).setAttribute('class','gx'+(on?' cur':''));$('gl'+k).setAttribute('class','gline'+(on?' cur':''))});
}
// ---------- recorded camera frames
const CAM=D.cam;
function camNear(t){let i=bs(CAM,t,c=>c[1]);if(i<0)return 0;if(i<CAM.length-1&&CAM[i+1][1]-t<t-CAM[i][1])i++;return i}
// ---------- camera card
let camK='rec',lastCam='';
$('seg').addEventListener('click',e=>{const k=e.target.closest('button')&&e.target.closest('button').dataset.k;if(!k)return;camK=k;[...$('seg').children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.k===k));lastCam='';drawCam(T)});
function drawCam(t){const im=$('camImg');
 if(camK==='rec'){const i=camNear(t),c=CAM[i],key='rec'+i;if(key===lastCam)return;lastCam=key;
  const d=c[1]-t;im.style.visibility='visible';im.src=thumbU(c[0]);im.alt='recorded frame '+c[0];im.dataset.full=fullU(c[0]);
  const out=t<CAM[0][1]-1?` · recording starts ${clk(CAM[0][1])}`:t>CAM[CAM.length-1][1]+1?' · recording has ended':'';
  $('camCap').innerHTML=`<strong>recorded frame ${c[0]}</strong> · ${clk(c[1])} (${Math.abs(d)<0.05?'±':d>0?'+':'−'}${Math.abs(d).toFixed(1)} s from the cursor)${out} · 320×240 thumbnail${D.thumbEvery>1?', every '+D.thumbEvery+'nd frame embedded':''}`;return}
 const i=bs(D.looks,t,l=>l.t);const key=camK+i;if(key===lastCam)return;lastCam=key;
 if(i<0){im.removeAttribute('src');im.style.visibility='hidden';$('camCap').textContent='no snapshot yet (first look at '+clk(D.looks[0].t)+')';return}
 const l=D.looks[i];const f=l[camK]||l.img;im.style.visibility='visible';im.src=imgU(f);im.dataset.full=im.src;im.alt=l.id+' '+camK;
 $('camCap').innerHTML=`<strong>${l.id}</strong> · ${clk(l.t)} · ${esc(l.c)}`}
$('camImg').addEventListener('click',()=>{const s=$('camImg').dataset.full;if(s)openOv(`<div class="ovh"><span>${esc($('camCap').textContent)}</span><span>Esc to close</span></div><img src="${s}">`)});
// ---------- recording video: video time = n / 10 s for camera frame n
const vid=$('vid');let vWant=-1,vLast=-1,vBusy=false,vTimer=0;
// a server without HTTP range requests (e.g. python -m http.server) makes the video unseekable: then load it once as a blob
let vBlob=false;
function unseekable(){const sk=vid.seekable;return /^https?:/.test(vid.currentSrc)&&isFinite(vid.duration)&&!(sk.length&&sk.end(sk.length-1)>=vid.duration-1)}
function loadBlob(){vBlob=true;console.info('video: no range support, loading as blob');$('vidCap').textContent='this server does not support seeking; loading the whole video once ('+D.vidMB+' MB)…';
 fetch(vid.currentSrc,{cache:'no-store'}).then(r=>{if(!r.ok)throw new Error(r.status);return r.blob()}).then(b=>{vLast=-1;vid.src=URL.createObjectURL(b)}).catch(e=>{vBlob=false;console.warn('video blob load failed',e);$('vidCap').textContent='video not seekable here ('+e.message+')'})}
function pump(){if(!vid||vBusy||vWant<0||vWant===vLast||!vid.paused||vid.readyState<1)return;if(unseekable()){if(!vBlob)loadBlob();return}vBusy=true;vLast=vWant;vid.currentTime=vWant/10+0.05;clearTimeout(vTimer);vTimer=setTimeout(()=>{vBusy=false;pump()},1500)}
function vidCap(){if(!vid)return;const n=Math.min(CAM.length-1,Math.max(0,Math.floor(vid.currentTime*10+1e-6)));
 $('vidCap').innerHTML=`video ${vid.currentTime.toFixed(1)} s = frame ${n} · ${clk(CAM[n][1])} · ${vid.paused?'paused, follows the cursor':'playing on its own (10× real time)'} · <button class="lnk" id="vjump">move the replay cursor here</button>`}
if(vid){vid.addEventListener('seeked',()=>{vBusy=false;clearTimeout(vTimer);vidCap();pump()});
 vid.addEventListener('loadedmetadata',()=>{vLast=-1;pump();vidCap()});if(vid.readyState>=1)setTimeout(()=>{vLast=-1;pump();vidCap()},0);
 vid.addEventListener('timeupdate',vidCap);vid.addEventListener('pause',vidCap);vid.addEventListener('play',vidCap);
 vid.addEventListener('error',()=>{const n=$('vmiss');if(n){n.hidden=false;vid.style.display='none'}});
 $('vidCap').addEventListener('click',e=>{if(e.target.id==='vjump'){const n=Math.min(CAM.length-1,Math.floor(vid.currentTime*10+1e-6));vid.pause();vLast=n;setT(CAM[n][1],'ui')}})}
function drawVid(t){if(!vid)return;vWant=CAM[camNear(t)][0];pump()}
// ---------- arm plot
const A=D.arm,NA=A.t.length;
const PL={x0:46,x1:486,z:[18,104],e:[124,168],g:[188,268]};
let pMode='all',pDrawn='';
const tip=$('tip');
$('pseg').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;pMode=b.dataset.k;[...$('pseg').children].forEach(x=>x.setAttribute('aria-pressed',x.dataset.k===pMode));pDrawn='';drawPlot(T)});
function pRange(t){if(pMode==='all')return [Math.min(T0,A.t[0]),Math.max(T1,A.t[NA-1])];return [t-60,t+60]}
function nice(span,target){const c=[0.001,0.002,0.005,0.01,0.02,0.05,0.1,0.2,0.5,1,2,5,10,20,50];for(const s of c)if(span/s<=target)return s;return 100}
function drawPlot(t){
 const [ta,tb]=pRange(t),key=pMode+(pMode==='win'?Math.round(t*4):'');
 const px=v=>PL.x0+(v-ta)/(tb-ta)*(PL.x1-PL.x0);
 const cx=px(Math.min(Math.max(t,ta),tb));
 if(key!==pDrawn){pDrawn=key;
  let i0=Math.max(0,bs(A.t,ta)),i1=Math.min(NA-1,bs(A.t,tb)+1);
  let zs=[];for(let i=i0;i<=i1;i++){if(A.z[i]!=null)zs.push(A.z[i]);if(A.cz[i]!=null)zs.push(A.cz[i])}
  D.servo.forEach(q=>{if(q.t>=ta&&q.t<=tb)zs.push(q.g[2],q.m[2])});
  let z0=zs.length?Math.min(...zs):0.4,z1=zs.length?Math.max(...zs):0.6;if(z1-z0<0.02){const c=(z0+z1)/2;z0=c-0.01;z1=c+0.01}
  const zp=(z1-z0)*0.06;z0-=zp;z1+=zp;
  let em=0;for(let i=i0;i<=i1;i++)if(A.e[i]!=null)em=Math.max(em,A.e[i]);em=Math.max(5,Math.ceil(em/5)*5);
  const zy=z=>PL.z[0]+(z1-z)/(z1-z0)*(PL.z[1]-PL.z[0]);
  const ey=e=>PL.e[1]-e/em*(PL.e[1]-PL.e[0]);
  const gy=g=>PL.g[1]-g/50*(PL.g[1]-PL.g[0]);
  const fy=f=>PL.g[1]-Math.min(f,40)/40*(PL.g[1]-PL.g[0]);
  let s='';
  // disabled spans
  let st=null;for(let i=i0;i<=i1+1;i++){const off=i<=i1&&A.en[i]===0;if(off&&st==null)st=i;if(!off&&st!=null){const a=px(A.t[st]-0.125),b=px(A.t[Math.min(i,i1)]+0.125);
   [PL.z,PL.e,PL.g].forEach(r=>{s+=`<rect class="off" x="${Math.max(PL.x0,a)}" width="${Math.max(0,Math.min(PL.x1,b)-Math.max(PL.x0,a))}" y="${r[0]}" height="${r[1]-r[0]}"/>`});st=null}}
  // grids + axes
  const zs_=nice(z1-z0,4);for(let z=Math.ceil(z0/zs_)*zs_;z<=z1;z+=zs_)s+=`<line class="gl" x1="${PL.x0}" x2="${PL.x1}" y1="${zy(z)}" y2="${zy(z)}"/><text class="ax" x="${PL.x0-4}" y="${zy(z)+3}" text-anchor="end">${z.toFixed(zs_<0.01?3:2)}</text>`;
  s+=`<text class="pl" x="${PL.x0}" y="${PL.z[0]-5}">TCP z (m)</text>`;
  [0,em/2,em].forEach(v=>{s+=`<line class="${v?'gl':'zl'}" x1="${PL.x0}" x2="${PL.x1}" y1="${ey(v)}" y2="${ey(v)}"/><text class="ax" x="${PL.x0-4}" y="${ey(v)+3}" text-anchor="end">${v}</text>`});
  s+=`<text class="pl" x="${PL.x0}" y="${PL.e[0]-5}">tracking error (mm)</text>`;
  [0,25,50].forEach(v=>{s+=`<line class="${v?'gl':'zl'}" x1="${PL.x0}" x2="${PL.x1}" y1="${gy(v)}" y2="${gy(v)}"/><text class="ax" x="${PL.x0-4}" y="${gy(v)+3}" text-anchor="end">${v}</text><text class="ax" x="${PL.x1+4}" y="${gy(v)+3}">${v*0.8}</text>`});
  s+=`<text class="pl" x="${PL.x0}" y="${PL.g[0]-5}">gripper gap (mm)</text><text class="pl" x="${PL.x1+30}" y="${PL.g[0]-5}" text-anchor="end">force (N)</text>`;
  const step=nice((tb-ta)/60,6)*60,fmt=step<60?(v=>clk(v)):(v=>clk(v).slice(0,5));
  for(let v=Math.ceil(ta/step)*step;v<tb;v+=step)s+=`<line class="gl" x1="${px(v)}" x2="${px(v)}" y1="${PL.g[1]}" y2="${PL.g[1]+4}"/><text class="ax" x="${px(v)}" y="${PL.g[1]+16}" text-anchor="middle">${fmt(v)}</text>`;
  // series
  const path=(arr,fy_)=>{let d='',pen=false;for(let i=i0;i<=i1;i++){const v=arr[i];if(v==null||(i>i0&&A.t[i]-A.t[i-1]>1)){pen=false;if(v==null)continue}d+=(pen?'L':'M')+px(A.t[i]).toFixed(1)+' '+fy_(v).toFixed(1);pen=true}return d};
  s+=`<path class="cz" d="${path(A.cz,zy)}"/><path class="mz" d="${path(A.z,zy)}"/><path class="er" d="${path(A.e,ey)}"/><path class="gp" d="${path(A.gap,gy)}"/><path class="fo" d="${path(A.f,fy)}"/>`;
  let lastClip=-99;for(let i=i0;i<=i1;i++)if(A.f[i]!=null&&A.f[i]>40){const x=px(A.t[i]);if(x-lastClip>6){s+=`<path class="clip" d="M${x-3.5} ${PL.g[0]+4}L${x+3.5} ${PL.g[0]+4}L${x} ${PL.g[0]-2}Z"><title>${clk(A.t[i])} force peak ${A.f[i]} N (clipped)</title></path>`;lastClip=x}}
  D.gev.forEach((g,k)=>{if(g.t<ta||g.t>tb)return;const x=px(g.t);s+=`<line class="gev" x1="${x}" x2="${x}" y1="${PL.z[0]}" y2="${PL.g[1]}"/><text class="gevl" x="${x+2}" y="${PL.g[0]+(k%2?22:12)}">${g.goal>0?'open':'close'} ${g.goal} mm</text>`});
  D.servo.forEach(q=>{if(q.t<ta||q.t>tb)return;const x=px(q.t);const en=Math.hypot(...q.e)*1000;
   s+=`<circle class="rg" cx="${x}" cy="${zy(q.g[2])}" r="2.6"/><circle class="rm" cx="${x}" cy="${zy(q.m[2])}" r="2.8"/><circle class="re" cx="${x}" cy="${ey(Math.min(en,em))}" r="2.4"/>`});
  s+=`<line class="cur" id="pcur" y1="${PL.z[0]-2}" y2="${PL.g[1]}"/><rect id="phit" x="${PL.x0}" y="${PL.z[0]}" width="${PL.x1-PL.x0}" height="${PL.g[1]-PL.z[0]}" fill="transparent"/>`;
  $('plot').innerHTML=s;PL.ta=ta;PL.tb=tb}
 const c=$('pcur');c.setAttribute('x1',cx);c.setAttribute('x2',cx);c.style.display=(t<ta||t>tb)?'none':''}
function plotT(e){const r=$('plot').getBoundingClientRect();const x=(e.clientX-r.left)/r.width*520;if(x<PL.x0||x>PL.x1)return null;return PL.ta+(x-PL.x0)/(PL.x1-PL.x0)*(PL.tb-PL.ta)}
const f1=v=>v==null?'–':v.toFixed(1),f3=v=>v==null?'–':v.toFixed(3);
$('plot').addEventListener('mousemove',e=>{const t=plotT(e);if(t==null){tip.style.display='none';return}
 let i=bs(A.t,t);if(i<0)i=0;if(i<NA-1&&A.t[i+1]-t<t-A.t[i])i++;
 let h=`${clk(A.t[i])} · arm ${A.en[i]?'enabled':'disabled'}<br>z ${f3(A.z[i])} (cmd ${f3(A.cz[i])}) m · error ${f1(A.e[i])} mm<br>gap ${f1(A.gap[i])} mm · force ${f1(A.f[i])} N`;
 const pxs=(PL.tb-PL.ta)/(PL.x1-PL.x0)*6;const q=D.servo.find(q=>Math.abs(q.t-t)<pxs);
 if(q)h+=`<br><strong>RESULT</strong> ${q.ph} · goal (${q.g.map(v=>v.toFixed(3)).join(', ')})<br>meas (${q.m.map(v=>v.toFixed(3)).join(', ')}) · err ${(Math.hypot(...q.e)*1000).toFixed(1)} mm`;
 const g=D.gev.find(g=>Math.abs(g.t-t)<pxs);if(g)h+=`<br><strong>gripper goal ${g.goal} mm</strong> · 2 s later ${g.gap2} mm, ${g.f2} N`;
 tip.innerHTML=h;const r=$('plotWrap').getBoundingClientRect();tip.style.display='block';let L=e.clientX-r.left+12;if(L>r.width-230)L=e.clientX-r.left-240;tip.style.left=Math.max(0,L)+'px';tip.style.top=(e.clientY-r.top+12)+'px'});
$('plot').addEventListener('mouseleave',()=>tip.style.display='none');
$('plot').addEventListener('click',e=>{const t=plotT(e);if(t!=null)setT(t,'ui')});
// ---------- call log
const log=$('log');
log.innerHTML=D.calls.map((c,i)=>{const bad=c.st&&c.st!==200?` <span class="bad">${c.st}</span>`:'';
 return `<div class="lr" data-i="${i}"><span class="tt">${clk(c.t)}</span><span class="nd ${c.node}">${c.node}</span><span class="pp">${c.m} ${esc(c.p)}${bad} <span class="ss">${esc(c.s)}</span></span></div>`}).join('');
$('logN').textContent=D.calls.length+' calls · click a row for JSON';
const rowsL=[...log.children];let lastCall=-2;
function drawLog(t,scroll){const i=bs(D.calls,t,c=>c.t);if(i===lastCall)return;
 rowsL.forEach((r,k)=>{r.classList.toggle('fut',k>i);r.classList.toggle('cur',k===i)});lastCall=i;
 $('logN').textContent=(i+1)+' / '+D.calls.length+' calls · click a row for JSON';
 if(scroll&&i>=0){const r=rowsL[i];const top=r.offsetTop-log.offsetTop;if(top<log.scrollTop+20||top>log.scrollTop+log.clientHeight-40)log.scrollTop=top-log.clientHeight/2}}
const RAW=__RAW__;
log.addEventListener('click',e=>{const r=e.target.closest('.lr');if(!r)return;const i=+r.dataset.i,c=D.calls[i];
 setT(c.t,'ui');
 openOv(`<div class="ovh"><span>${clk(c.t)} · ${c.node} ${c.m} ${esc(c.p)}</span><span>Esc or click outside to close</span></div>`+(c.img||[]).map(f=>`<img src="${imgU(f)}" alt="${f}" loading="lazy"><div class="muted">img/${f}</div>`).join('')+`<pre>${esc(JSON.stringify(RAW[i],null,1))}</pre>`)});
// ---------- overlay
const ov=$('ov');function openOv(h){$('ovb').innerHTML=h;ov.classList.add('on')}
ov.addEventListener('click',e=>{if(e.target===ov)ov.classList.remove('on')});
document.addEventListener('keydown',e=>{if(e.key==='Escape')ov.classList.remove('on')});
document.addEventListener('click',e=>{const im=e.target.closest('#tl figure img, .doc figure img');if(im)openOv(`<div class="ovh"><span>${esc(im.alt)}</span><span>Esc to close</span></div><img src="${im.getAttribute('src')}">`)});
// ---------- transcript sync
const MQ=window.matchMedia('(max-width:900px)');const mobile=()=>MQ.matches;
function place(){if(mobile()){if($('row2').parentNode!==$('mini'))$('mini').appendChild($('row2'))}else if($('row2').parentNode!==$('rv'))$('rv').prepend($('row2'))}
place();MQ.addEventListener('change',place);
$('vtog').addEventListener('click',()=>{const off=$('mini').classList.toggle('off');$('vtog').setAttribute('aria-pressed',!off)});
const refLine=()=>{const b=document.querySelector('.ctrl').getBoundingClientRect().bottom;return b+(window.innerHeight-b)*0.25};
function markEv(i,scroll){if(i===curEv)return;if(curEv>=0)evEls[curEv].classList.remove('now');curEv=i;if(i<0)return;evEls[i].classList.add('now');
 if(scroll){progScroll=Date.now();const e=evEls[i];
  if(mobile()){const y=e.getBoundingClientRect().top+window.scrollY-refLine()+4;window.scrollTo({top:y})}
  else{tl.scrollTop=e.offsetTop-tl.offsetTop-tl.clientHeight*0.3}}}
function setT(t,src){T=Math.min(Math.max(t,T0),T1);rng.value=T;
 $('clock').textContent=clk(T)+' EST · '+el(T);
 drawMap(T);drawCam(T);drawVid(T);drawPlot(T);drawLog(T,true);
 if(src!=='scroll')markEv(bs(EV,T),true)}
function onScroll(){if(Date.now()-progScroll<120||playing)return;
 let refY;if(mobile()){refY=refLine()}else{const r=tl.getBoundingClientRect();refY=r.top+tl.clientHeight*0.3}
 let lo=0,hi=evEls.length-1,best=0;while(lo<=hi){const m=(lo+hi)>>1;if(evEls[m].getBoundingClientRect().top<=refY){best=m;lo=m+1}else hi=m-1}
 markEv(best,false);setT(EV[best],'scroll')}
tl.addEventListener('scroll',onScroll,{passive:true});
window.addEventListener('scroll',()=>{if(mobile())onScroll()},{passive:true});
tl.addEventListener('click',e=>{if(e.target.classList.contains('t')){const ev=e.target.closest('.ev');if(ev){const i=+ev.dataset.i;setT(EV[i],'ui')}}});
rng.addEventListener('input',()=>{stop();setT(+rng.value,'ui')});
// ---------- play
const pb=$('play');
function stop(){playing=false;pb.innerHTML='&#9654; Play'}
function frame(ts){if(!playing)return;const dt=lastF?(ts-lastF)/1000:0;lastF=ts;let n=T+dt*(+$('speed').value);const ne=EV[bs(EV,T)+1],nc=(D.calls[bs(D.calls,T,c=>c.t)+1]||{}).t;const nx=Math.min(ne||Infinity,nc||Infinity);if(nx-T>45&&n<nx)n=Math.max(n,nx-3);if(n>=T1){setT(T1,'play');stop();return}setT(n,'play');requestAnimationFrame(frame)}
pb.addEventListener('click',()=>{if(playing){stop();return}if(T>=T1)setT(T0,'ui');playing=true;lastF=0;pb.innerHTML='&#10074;&#10074; Pause';requestAnimationFrame(frame)});
document.addEventListener('keydown',e=>{if(e.target.closest('input,select,textarea,video')&&e.key!==' ')return;if(e.target.closest('video'))return;if($('tab-replay').hidden)return;
 if(e.key===' '){e.preventDefault();pb.click()}
 else if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.preventDefault();stop();const i=bs(EV,T);const j=e.key==='ArrowRight'?Math.min(EV.length-1,i+1):Math.max(0,i-(EV[i]<T?0:1));setT(EV[j],'ui')}});
// ---------- tabs + hash links
function showTab(k){document.querySelectorAll('.tabs button').forEach(b=>b.setAttribute('aria-selected',b.dataset.tab===k));document.querySelectorAll('.tab').forEach(s=>s.hidden=s.id!=='tab-'+k);if(k!=='replay'){stop();if(vid&&!vid.paused)vid.pause()}}
document.querySelector('.tabs').addEventListener('click',e=>{const b=e.target.closest('button');if(b)showTab(b.dataset.tab)});
function go(h){if(!h||h==='#')return;const t=document.getElementById(h.slice(1));if(!t)return;const tab=t.closest('.tab');if(tab)showTab(tab.id.slice(4));
 if(t.classList.contains('ev')){setT(EV[+t.dataset.i],'ui');window.scrollTo({top:document.querySelector('.ctrl').getBoundingClientRect().top+window.scrollY});markEv(-1);curEv=-1;markEv(+t.dataset.i,true);return}
 if(t.tagName==='DETAILS'){t.open=true;document.querySelectorAll('.cmdent.hl').forEach(x=>x.classList.remove('hl'));t.classList.add('hl')}
 t.scrollIntoView({block:'start'})}
document.addEventListener('click',e=>{const a=e.target.closest('a[href^="#"]');if(!a)return;e.preventDefault();history.replaceState(null,'',a.getAttribute('href'));go(a.getAttribute('href'))});
setT(T0,'ui');tl.scrollTop=0;
if(location.hash)go(location.hash);
window.addEventListener('hashchange',()=>go(location.hash));
})();
</script>
</body></html>
"""

VIDEO_REL = "streams/derived/review_10x.mp4"
post_note = ""
if post_calls:
    kinds = sorted({f"{c['node']} {c['method']} /{c['path']}" for c in post_calls})
    post_note = (f"<div class='muted'>Ends at the nav session close ({clock(CALLS_END)}). <code>calls.jsonl</code> has {len(post_calls):,} later "
                 f"entries ({clock(post_calls[0]['t'])}&ndash;{clock(post_calls[-1]['t'])}: {esc(', '.join(kinds))}), logged after the run; they are not shown.</div>")
elif os.path.exists(P("calls_post_run_audit_ik.jsonl")):
    n_post = sum(1 for _ in open(P("calls_post_run_audit_ik.jsonl")))
    post_note = (f"<div class='muted'>Ends at the nav session close ({clock(CALLS_END)}). {n_post:,} read-only arm <code>/ik</code> checks made after the run "
                 f"by a separate audit session (see <code>AUDIT.md</code>) are kept apart in <code>calls_post_run_audit_ik.jsonl</code>.</div>")


def video_html(mode):
    """mode: 'rel' (index.html), 'sa-embed' (standalone, data URI), 'sa-side' (standalone, file ships alongside)."""
    if mode == "sa-embed":
        src = "data:video/mp4;base64," + base64.b64encode(open(video_path, "rb").read()).decode()
        return f"<video id='vid' controls muted playsinline preload='auto' src='{src}'></video>"
    v = f"<video id='vid' controls muted playsinline preload='metadata' src='{VIDEO_REL}'></video>"
    miss = (f"<div class='vnote' id='vmiss' hidden>The video file was not found at <a href='{VIDEO_REL}'>{VIDEO_REL}</a> "
            f"next to this page.</div>")
    if mode == "sa-side":
        return (v + f"<div class='vnote'>The video ({video_bytes / 1e6:.0f}&nbsp;MB) is not embedded in this standalone file. It ships alongside as "
                f"<a href='{VIDEO_REL}'><code>{VIDEO_REL}</code></a>; the player above loads it when this page sits in the episode folder.</div>"
                + miss.replace("<div class='vnote' id='vmiss' hidden>", "<div class='vnote' id='vmiss' hidden><strong>Not available here.</strong> "))
    return v + miss


def render(mode, thumb_every=1):
    cam_d = cam if thumb_every == 1 else [c for c in cam if c[0] % thumb_every == 0]
    data = {"ev": EV, "t0": T0, "t1": T1, "calls": C, "looks": looks, "goals": goals, "servo": servo, "grips": grips,
            "pose": pose, "phases": phases, "ticks": sorted(ticks), "tz": -5 * 3600,
            "body": {"fp": 0.432, "hfov": 82.7, "camyaw": -4.0},
            "arm": arm, "gev": gev, "cam": cam_d, "thumbEvery": thumb_every, "camFull": mode == "rel", "vidMB": round(video_bytes / 1e6)}
    data_json = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    raw = [{k: c.get(k) for k in ("t", "node", "method", "path", "body", "status", "resp")} for c in calls]
    raw_json = json.dumps(raw, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    fmax = max(v for v in arm["f"] if v is not None)
    gids = [g["id"] for g in goals]
    return (TEMPLATE.replace("__TRANSCRIPT__", transcript_html)
            .replace("__TOOLS__", tools_html).replace("__CMDS__", "\n".join(cmd_html)).replace("__README__", readme_html)
            .replace("__INTERVIEW__", interview_html).replace("__VIDEO__", video_html(mode))
            .replace("__START__", clock(T0)[:5]).replace("__END__", clock(T1)[:5])
            .replace("__RMIN__", f"{robot_min:.1f}").replace("__NLOOK__", str(nlooks)).replace("__NQ__", str(nq))
            .replace("__NGOAL__", str(len(goals))).replace("__GID__", f"{min(gids)}&ndash;{max(gids)}").replace("__GRES__", esc(goal_txt))
            .replace("__NSERVO__", str(len(servo))).replace("__NGRIP__", str(len(grips))).replace("__HELD__", f"{held_min:.0f}")
            .replace("__TRAVEL__", f"{travel:.2f}").replace("__NCAM__", f"{len(cam):,}").replace("__CAMMIN__", f"{cam_min:.0f}")
            .replace("__ARMHZ__", f"{arm_rate:.0f}").replace("__FMAX__", f"{fmax:.0f}")
            .replace("__NERR__", str(cmd_flags["error"])).replace("__NDEN__", str(cmd_flags["denied"])).replace("__NCMD__", str(len(cmd_html)))
            .replace("__POSTNOTE__", post_note)
            .replace("__DATA__", data_json).replace("__RAW__", raw_json))


out = render("rel")
with open(P("index.html"), "w") as f:
    f.write(out)
print(f"index.html: {len(out)/1e6:.2f} MB, {len(events)} transcript events ({n_omit} interview entries omitted), {len(cmd_html)} command entries, "
      f"{len(pose)} pose points from {n_base_rows} base rows, travel {travel:.3f} m, {len(arm['t'])} arm bins from {n_arm_rows} rows, "
      f"{len(cam)} camera frames, images shown {nimg}, errors/denials in transcript {flags}, in commands.md {cmd_flags}")


# ---------------------------------------------------------------- standalone export (one file, images embedded)
# Every img/ file the page names is embedded once as a data URI in window.IMG; every recorded thumbnail in
# window.THUMB (or every 2nd one, if the page would exceed SA_MAX). Markup img srcs resolve through IMG at
# load; the script resolves through imgU()/thumbU(). The relative-path page is left as it is.
def b64(path, mime):
    return f"data:{mime};base64," + base64.b64encode(open(path, "rb").read()).decode()


def standalone(thumb_every):
    vmode = "sa-embed" if video_bytes <= VIDEO_EMBED_MAX else "sa-side"
    page = render(vmode, thumb_every)
    used = sorted(f for f in imgs if f in page)
    IMG = {f: b64(P("img", f), "image/png" if f.endswith(".png") else "image/jpeg") for f in used}
    THUMB = {c[0]: b64(thumb_path(c[0]), "image/jpeg") for c in cam if c[0] % thumb_every == 0}
    sa = re.sub(r"""src=(['"])img/([\w.\-]+)\1""",
                lambda m: f"src={m.group(1)}data:image/gif;base64,R0lGODlhAQABAAAAACw={m.group(1)} data-img={m.group(1)}{m.group(2)}{m.group(1)}"
                if m.group(2) in IMG else m.group(0), page)
    boot = ("<script>window.IMG=" + json.dumps(IMG, separators=(",", ":")) + ";window.THUMB=" + json.dumps(THUMB, separators=(",", ":"))
            + ";document.addEventListener('DOMContentLoaded',()=>{for(const i of document.querySelectorAll('img[data-img]'))i.src=window.IMG[i.dataset.img];});</script>")
    sa = sa.replace("<head>", "<head>" + boot, 1)
    missing = re.findall(r"""src=['"]img/([\w.\-]+)""", sa)
    assert not missing, missing
    return sa, len(IMG), len(THUMB), vmode


sa, nI, nT, vmode = standalone(1)
if len(sa) > SA_MAX:
    sa, nI, nT, vmode = standalone(2)
with open(P(SA_NAME), "w") as f:
    f.write(sa)
print(f"{SA_NAME} (standalone): {len(sa)/1e6:.1f} MB, {nI} images, {nT} thumbnails embedded, video {vmode} ({video_bytes/1e6:.1f} MB)")
