"""Realistic tool bodies for the seeded demo challenge.

`seed_demo.py` used to save every tool with the source `# generated`, which was fine
when nothing could open a tool. Now that the dashboard renders them, placeholder
sources make the most important screen in the demo look broken.

These are the shapes the Toolwright actually emits, per its prompt: a self-contained
HTML document for `mini_app`, structured JSON for `checklist`, Python for
`calculator`/`tracker`/`drill`, and plain text for `script`/`research_brief`.
"""

from __future__ import annotations

PACING_CALCULATOR = '''\
"""Video Pacing Calculator - keeps a demo video under a hard time cap."""


def pacing(beats, cap_seconds=240):
    """beats: list of (name, seconds). Returns per-beat share and headroom."""
    total = sum(seconds for _, seconds in beats)
    return {
        "total_seconds": total,
        "cap_seconds": cap_seconds,
        "headroom_seconds": cap_seconds - total,
        "over_cap": total > cap_seconds,
        "breakdown": [
            {"beat": name, "seconds": s, "percent": round(100 * s / total, 1)}
            for name, s in beats
        ],
    }


if __name__ == "__main__":
    result = pacing([
        ("hook", 20), ("interview", 30), ("graph", 30),
        ("forge", 60), ("teammate", 30), ("feedback", 15),
        ("copy-out", 15), ("architecture", 15), ("close", 10),
    ])
    print(f"total {result['total_seconds']}s of {result['cap_seconds']}s "
          f"({result['headroom_seconds']}s spare)")
    for row in result["breakdown"]:
        print(f"  {row['beat']:<14} {row['seconds']:>3}s  {row['percent']:>5}%")
'''

BACKEND_CHECKLIST = '''\
{
  "title": "Backend Verification Checklist",
  "items": [
    {"text": "GET /api/healthz returns ok:true",
     "note": "If store reads \\"memory\\" on a deployment, Firestore fell back silently."},
    {"text": "Create a session, then POST one turn to /run_sse",
     "note": "deploy\\\\smoke_live.ps1 does both and prints what the agent said."},
    {"text": "Confirm the agent reply came from Vertex, not a local key",
     "note": "Gemini 3.x is served from the global endpoint, not a regional one."},
    {"text": "Open /app and send a goal end to end",
     "note": "The map should draw and the header title should fill itself in."},
    {"text": "Check a forged tool actually opens",
     "note": "A tool you cannot open is a screenshot of a tool."},
    {"text": "Delete the session mid-conversation and send another turn",
     "note": "scripts\\\\check_session_recovery.py automates this."}
  ]
}
'''

HOSTING_BRIEF = '''\
Non-GCP Hosting Comparison
==========================

Why this exists: Cloud Run requires billing enabled, and nobody on the team has
admin on the billing account. This brief exists so the blocker does not stop the
graph -- it reshapes it.

Render
  Free tier sleeps after 15 min idle; ~30s cold start. Fine for a judge clicking a
  link, fatal for a live demo. Deploys from a Dockerfile with no card on file.

Vercel
  Excellent for the static dashboard. Serverless functions cap at 10s on the free
  tier, which is shorter than one FORGE turn -- so the agent service cannot live
  here. Split: UI on Vercel, agents elsewhere.

Fly.io
  Closest match to Cloud Run. Scale-to-zero with fast wake, Dockerfile deploys,
  free allowance covers a demo. Requires a card even on the free plan.

Recommendation
  Fly.io for the agent service, Vercel for the dashboard, if and only if the
  billing blocker holds. Revisit the moment admin access lands -- Cloud Run plus
  Firestore is one fewer moving part and it is what the architecture assumes.
'''

DEMO_SCRIPT_TEMPLATE = '''\
4-Minute Demo Script Template
=============================

Hard cap 4:00. Target 3:45 so an encode hiccup cannot disqualify you.

0:00  Hook. The problem in one sentence, in your own voice.
0:20  Show the real thing being asked a real question.
0:50  Show the structure that appears -- not a list, a graph.
1:20  THE MONEY SHOT. The tool is written, executed, tested, and used.
2:20  Second window. Someone else inherits what you learned.
2:50  Say something is not useful. Watch it change.
3:05  Take the output somewhere else.
3:20  Proof it is deployed: console, health endpoint.
3:35  What it costs and where to try it.

Rules
  Narrate value, not UI. Never say "in a real product we would".
  If a live build fails, cut to the seeded run and say nothing.
'''

STATE_SIMULATOR = '''\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Agent Execution State</title>
<style>
  body{margin:0;font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    background:#0F1218;color:#EDEFF3;padding:20px}
  h1{font-size:15px;margin:0 0 4px;letter-spacing:.3px}
  p.sub{margin:0 0 18px;color:#8B93A7;font-size:12.5px}
  .row{display:flex;align-items:center;gap:12px;padding:10px 12px;margin-bottom:8px;
    border:1px solid #232838;border-radius:10px;background:#151922}
  .row b{width:130px;font-weight:650;font-size:13px}
  .bar{flex:1;height:8px;border-radius:99px;background:#1C2130;overflow:hidden}
  .fill{height:100%;width:0;border-radius:99px;transition:width .4s ease;
    background:linear-gradient(90deg,#3DD68C,#7FB2FF)}
  .pct{width:44px;text-align:right;font-variant-numeric:tabular-nums;color:#8B93A7;
    font-size:12px}
  button{background:linear-gradient(135deg,#3A6FD8,#4C8DFF);color:#fff;border:0;
    border-radius:9px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer}
  button:disabled{opacity:.5;cursor:not-allowed}
  #done{margin-top:14px;color:#3DD68C;font-size:13px;height:18px}
</style>
</head>
<body>
<h1>Agent Execution State</h1>
<p class="sub">Four Toolwrights, one queue. Press start to watch the fan-out drain it.</p>
<div id="rows"></div>
<button id="go">Start</button>
<div id="done"></div>
<script>
  const workers = ["toolwright_0","toolwright_1","toolwright_2","toolwright_3"];
  const rows = document.getElementById("rows");
  const bars = workers.map(name => {
    const row = document.createElement("div");
    row.className = "row";
    row.innerHTML = '<b>' + name + '</b>' +
      '<div class="bar"><div class="fill"></div></div><div class="pct">0%</div>';
    rows.appendChild(row);
    return {fill: row.querySelector(".fill"), pct: row.querySelector(".pct")};
  });

  document.getElementById("go").onclick = function () {
    const btn = this;
    btn.disabled = true;
    document.getElementById("done").textContent = "";
    let finished = 0;
    bars.forEach(function (bar, i) {
      let p = 0;
      const speed = 6 + Math.random() * 10;
      const timer = setInterval(function () {
        p = Math.min(100, p + speed);
        bar.fill.style.width = p + "%";
        bar.pct.textContent = Math.round(p) + "%";
        if (p >= 100) {
          clearInterval(timer);
          if (++finished === bars.length) {
            document.getElementById("done").textContent =
              "All slots drained \\u2014 6 tools saved.";
            btn.disabled = false;
          }
        }
      }, 120 + i * 30);
    });
  };
</script>
</body>
</html>
'''

#: node_id -> (source, usage)
BODIES: dict[str, tuple[str, str]] = {
    "verify-agent-backend": (
        BACKEND_CHECKLIST,
        "Tick these off in order. Anything that fails tells you exactly which layer "
        "broke, so you are never guessing which half of the stack is at fault.",
    ),
    "demo-video-script": (
        DEMO_SCRIPT_TEMPLATE,
        "A beat sheet with the timings already summing to under four minutes. "
        "Rewrite the words; keep the clock.",
    ),
    "edit-demo": (
        PACING_CALCULATOR,
        "Give it your beats and their lengths. It tells you the total, how much "
        "headroom is left against the four-minute cap, and which beat is eating "
        "your video.",
    ),
    "alt-hosting": (
        HOSTING_BRIEF,
        "Three hosts compared on the one thing that actually blocked you -- getting "
        "a demo online without billing admin -- with a recommendation at the end.",
    ),
    "goal-graph-view": (
        STATE_SIMULATOR,
        "Press Start. This is what the parallel FORGE stage is doing while the "
        "journal fills: four workers pulling from one queue until it is empty.",
    ),
}
