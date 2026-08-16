"""Cut the recorded footage into a submission video.

Reads `_video/marks.json` -- the beat timestamps `record_demo.py` wrote while it drove
the product -- and assembles a captioned MP4.

Two editing decisions worth stating out loud, because a demo video is a claim:

  * **The FORGE build is sped up.** It really takes three to five minutes. Speeding it
    up is honest; cutting to the finished map and implying it was instant is not, so
    the caption says the real elapsed time on screen while it runs fast.
  * **Nothing is re-staged.** Every frame is the deployed service. The one thing the
    camera does not show is the Google popup itself: the recorder signs in with a
    custom token, because a popup cannot be automated. The gate is real, the token is
    real, the session is real -- but if you want the popup on film, record that beat
    yourself and drop it in.

    python scripts\\cut_demo.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "_video"
RAW = OUT / "raw"
WORK = OUT / "work"
FINAL = OUT / "challenge-accepted-demo.mp4"

W, H = 1280, 720
FPS = 30
#: Type scales with the frame, so captions stay the same size relative to the picture.
K = W / 1600

#: The shot list. Each entry:
#:   ctx    -- which recording it comes from
#:   from/to-- beat names in marks.json (or a number of seconds after `from`)
#:   speed  -- 1 = real time; 8 = eight times faster
#:   cap    -- the caption burnt into the lower third
#:   sub    -- smaller second line, used for the honest elapsed-time note
SHOTS = [
    dict(ctx="owner", frm="gate", dur=3.0, speed=1,
         cap="Quests are shared, so the app needs to know who you are",
         sub="Google Sign-In, verified server-side"),
    dict(ctx="owner", frm="turn1-typing", to="turn1-done", speed=1.25,
         cap="Name something you want to be true that isn't yet"),
    dict(ctx="owner", frm="turn2-typing", to="turn3-done", speed=2.2,
         cap="It asks only questions whose answer would change the plan",
         sub="five to nine, then it stops"),
    dict(ctx="owner", frm="turn4-sent", to="map-drawn", speed=5,
         cap="The Cartographer turns the charter into a dependency graph",
         sub="micro-tasks under two hours, with written acceptance criteria"),
    # 210s of building. At 4.5x that is a 47-second hold, which is longer than the
    # rest of the video put together; 9x keeps the whole build on screen without the
    # viewer wondering when it ends.
    dict(ctx="owner", frm="map-drawn", to="turn4-done", speed=9,
         cap="Four Toolwrights build in parallel — each writes code, runs it, "
             "and smoke-tests it",
         sub="this really takes about four minutes; the footage is sped up"),
    dict(ctx="owner", frm="node-selected", dur=3.4, speed=1,
         cap="Every step that needs a tool has one"),
    dict(ctx="owner", frm="tool-open", dur=6.0, speed=1,
         cap="Not a description of a tool. The tool, and you can run it."),
    dict(ctx="owner", frm="invite-copied", dur=2.6, speed=1,
         cap="Invite someone into the same quest"),
    dict(ctx="mate", frm="invited", dur=3.4, speed=1,
         cap="A link is an invitation to join — not a way around the door"),
    dict(ctx="mate", frm="joined", to="mate-party", speed=1.2,
         cap="They inherit the map, the tools, and what the interview already learned",
         sub="goal-scoped memory, shared across the party"),
    dict(ctx="owner", frm="roster-grew", dur=3.4, speed=1,
         cap="The owner's roster grows while they sit still"),
    dict(ctx="owner", frm="theme-light", dur=3.0, speed=1,
         cap="Dark or light — both measured for contrast, not eyeballed"),
]

TITLE = ("CHALLENGE ACCEPTED",
         "Agents that don't just plan your goal —\nthey build the tools each step needs.")
ENDCARD = ("challengeaccepted.app",
           "Google ADK · Gemini 3.6 Flash · Cloud Run · Firestore · Memory Bank")


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def run(args: list[str]) -> None:
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode != 0:
        _p(" ".join(args[:12]) + " ...")
        _p(r.stderr[-1500:])
        raise SystemExit("ffmpeg failed")


def card(path: Path, title: str, body: str, big: int = 60, small: int = 25) -> None:
    """A title card, drawn with PIL so the type is not at the mercy of drawtext escaping."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (W, H), "#0B0D12")
    d = ImageDraw.Draw(img)
    # The app's own wash, so the cards belong to the same piece.
    for i in range(H):
        k = i / H
        d.line([(0, i), (W, i)],
               fill=(11 + int(10 * k), 13 + int(12 * k), 18 + int(24 * k)))

    def font(sz: int, bold: bool = True):
        for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
            try:
                return ImageFont.truetype(f"C:/Windows/Fonts/{name}", sz)
            except OSError:
                continue
        return ImageFont.load_default()

    f1, f2 = font(big), font(small, bold=False)
    tw = d.textbbox((0, 0), title, font=f1)
    d.text(((W - tw[2]) / 2, H / 2 - 90), title, font=f1, fill="#EDEFF3")
    y = H / 2 + 20
    for line in body.split("\n"):
        lw = d.textbbox((0, 0), line, font=f2)
        d.text(((W - lw[2]) / 2, y), line, font=f2, fill="#8B93A7")
        y += small * 1.6
    img.save(path)


def caption(path: Path, text: str, sub: str | None) -> None:
    """A lower third with alpha, overlaid on the footage."""
    from PIL import Image, ImageDraw, ImageFont

    bar_h = int(150 * K)
    img = Image.new("RGBA", (W, bar_h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([int(32 * K), int(16 * K), W - int(32 * K), bar_h - int(16 * K)],
                        radius=int(16 * K), fill=(11, 13, 18, 232))

    def font(sz: int, bold: bool):
        for name in (("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")):
            try:
                return ImageFont.truetype(f"C:/Windows/Fonts/{name}", sz)
            except OSError:
                continue
        return ImageFont.load_default()

    f1, f2 = font(int(30 * K) + 4, True), font(int(21 * K) + 3, False)
    x = int(58 * K)
    d.text((x, int((38 if sub else 52) * K)), text, font=f1, fill=(237, 239, 243))
    if sub:
        d.text((x, int(80 * K)), sub, font=f2, fill=(139, 147, 167))
    img.save(path)


def main() -> int:
    marks_path = OUT / "marks.json"
    if not marks_path.exists():
        sys.exit("No _video/marks.json -- run scripts\\record_demo.py first.")
    data = json.loads(marks_path.read_text(encoding="utf-8"))
    beats = {(b["ctx"], b["beat"]): b["t"] for b in data["beats"]}
    WORK.mkdir(parents=True, exist_ok=True)

    _p("beats recorded:")
    for (ctx, beat), t in beats.items():
        _p(f"  {ctx:<6} {beat:<16} {t:>8.2f}s")

    segments: list[Path] = []

    intro = WORK / "card_intro.png"
    card(intro, *TITLE)
    seg = WORK / "00_intro.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", "3.2", "-i", str(intro),
         "-vf", f"fps={FPS},format=yuv420p,fade=in:0:15,fade=out:80:16",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(seg)])
    segments.append(seg)

    for i, shot in enumerate(SHOTS, 1):
        ctx = shot["ctx"]
        src = RAW / data["videos"][ctx]
        start = beats.get((ctx, shot["frm"]))
        if start is None:
            _p(f"  skip {shot['frm']}: never happened in this run")
            continue
        if "to" in shot:
            end = beats.get((ctx, shot["to"]))
            if end is None:
                _p(f"  skip {shot['frm']}->{shot['to']}: no end beat")
                continue
        else:
            end = start + shot["dur"]
        length = max(0.5, end - start)
        speed = shot["speed"]

        cap_png = WORK / f"cap_{i:02d}.png"
        caption(cap_png, shot["cap"], shot.get("sub"))
        out = WORK / f"{i:02d}_{shot['frm']}.mp4"
        # setpts speeds the picture up; the caption is overlaid AFTER, so text speed is
        # unaffected by the ramp -- a caption that flashes past at 10x is not a caption.
        vf = (f"trim=start={start}:duration={length},setpts=(PTS-STARTPTS)/{speed},"
              f"fps={FPS},scale={W}:{H}")
        run(["ffmpeg", "-y", "-i", str(src), "-i", str(cap_png),
             "-filter_complex",
             f"[0:v]{vf}[v];[v][1:v]overlay=0:H-{int(158 * K)}:format=auto[o]",
             "-map", "[o]", "-an", "-c:v", "libx264", "-preset", "medium",
             "-crf", "18", "-pix_fmt", "yuv420p", str(out)])
        segments.append(out)
        _p(f"  cut {out.name}  {length:.1f}s at {speed}x -> {length/speed:.1f}s")

    endp = WORK / "card_end.png"
    card(endp, *ENDCARD, big=50, small=21)
    seg = WORK / "99_end.mp4"
    run(["ffmpeg", "-y", "-loop", "1", "-t", "3.4", "-i", str(endp),
         "-vf", f"fps={FPS},format=yuv420p,fade=in:0:15,fade=out:85:16",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(seg)])
    segments.append(seg)

    listing = WORK / "concat.txt"
    listing.write_text(
        "".join(f"file '{p.as_posix()}'\n" for p in segments), encoding="utf-8")
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(listing),
         "-c:v", "libx264", "-preset", "slow", "-crf", "19", "-pix_fmt", "yuv420p",
         "-movflags", "+faststart", str(FINAL)])

    dur = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(FINAL)],
        capture_output=True, text=True).stdout.strip()
    _p(f"\nwrote {FINAL}  ({FINAL.stat().st_size/1e6:.1f} MB, {float(dur):.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
