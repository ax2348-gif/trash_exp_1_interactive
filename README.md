# Robot episode replay: foam block → trash can (2026-11-10)

A static replay of an agent-driven mobile-manipulation run on a swerve base with a 6-DoF arm. `index.html` at the root is the page, ready
for GitHub Pages. It needs no build step or server code.

The page shows:
- the agent's transcript, verbatim;
- the robot view synced to a scrubber: the base trajectory, a 1 Hz recorded camera, a 10× review video, and arm and gripper telemetry;
- tabs for the improvised tools, the README and the post-experiment interview.

Everything here, including the raw data, stops at the episode end: the operator's "terminate the session" at 21:45:12 local.

## Layout

| path | what |
|---|---|
| `index.html` | the replay page (all data embedded; images and video loaded from the folders below) |
| `img/` | snapshots, query overlays, BEVs and zoom crops the agent looked at |
| `streams/derived/cam_thumbs/` | 1 Hz camera thumbnails (the camera card's "recorded" mode) |
| `streams/derived/review_10x.mp4` | review video: colour, depth and a top-down world map, 10× speed (47.6 MiB) |
| `streams/cam/*_color.jpg` | full-resolution 1 Hz colour frames (opened by clicking the recorded frame) |
| `episode/` | the episode's README (outcome, findings checked against the recordings), TOOLS.md, INTERVIEW.md, AUDIT.md, `calls.jsonl` (every robot call) and the improvised tools (`tools/`, including `commands.md`, every command verbatim) |
| `.nojekyll` | serve files as-is (no Jekyll processing) |

**Not included:**
- **The raw transcript (`claude_transcript.jsonl`).** It contains the account email in its session metadata. The page's link to it will 404.
- **The raw stream recordings.** They are on the separate **[`raw-data`](../../tree/raw-data) branch**, kept off `main` so the Pages site
  stays small. It holds:
  - the arm stream incl. **TCP** at ~49 Hz, and the base estimator stream (gzip);
  - 2,139 depth and colour frames (to the episode end, 21:45:12), with stream metadata and calibration;
  - decoded CSVs, the robot description, call logs, the nav session export and the recorder logs;
  - a reader and checksums.

  Fetch it alone with `git clone --single-branch --branch raw-data <repo-url>`.

The transcript shown on the page includes the robot's (private) Tailscale hostname and local file paths, reproduced verbatim.

## Publish on GitHub Pages

1. Create an empty repository on GitHub, then:

   ```bash
   git remote add origin git@github.com:<owner>/<repo>.git
   git push -u origin main
   ```

2. Enable Pages once: **Settings → Pages → Build and deployment → Source: Deploy from a branch → `main` / `/ (root)`**. Or with the GitHub CLI:

   ```bash
   gh api -X POST repos/<owner>/<repo>/pages -f "source[branch]=main" -f "source[path]=/"
   ```

3. The page appears at `https://<owner>.github.io/<repo>/` after a minute or two. Every later push to `main` redeploys it.

Pages needs a public repository on the free plan (private repositories need a paid plan). GitHub Pages serves video with
range requests, so seeking works.

## Updating

The page is generated in the source repo by `docs/episodes/2026-11-10-trash-can/tools/build_html.py`. Copy the regenerated
`index.html` here, along with any new files under `img/` or `streams/derived/`.
