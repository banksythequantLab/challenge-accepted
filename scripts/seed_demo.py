"""Seed a realistic challenge into the store, with no model calls.

Lets you open the dashboard and see a populated graph in one second instead of paying
for a live run. Also what the UI tests render against.

    python scripts\\seed_demo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from challenge_accepted.services.store import store  # noqa: E402

NODES = [
    ("verify-agent-backend", "Verify agent backend", [], "done", 60),
    ("demo-video-script", "Draft the 4-minute script", [], "done", 90),
    ("frontend-shell", "Next.js shell + auth", [], "active", 120),
    ("stream-agent-events", "Stream agent events to the UI",
     ["verify-agent-backend", "frontend-shell"], "todo", 120),
    ("goal-graph-view", "Render the goal graph", ["frontend-shell"], "todo", 120),
    ("alt-hosting", "Pick hosting that isn't Cloud Run", [], "blocked", 60),
    ("deploy-app", "Deploy behind microgoals.app",
     ["stream-agent-events", "goal-graph-view", "alt-hosting"], "todo", 90),
    ("e2e-walkthrough", "Walk the whole flow", ["deploy-app"], "todo", 60),
    ("record-demo", "Record the demo", ["e2e-walkthrough", "demo-video-script"], "todo", 90),
    ("edit-demo", "Cut it to 3:45", ["record-demo"], "todo", 120),
    ("devpost-submission", "Submit on Devpost", ["edit-demo"], "todo", 45),
]

TOOLS = [
    ("verify-agent-backend", "checklist", "Backend Verification Checklist"),
    ("demo-video-script", "script", "4-Minute Demo Script Template"),
    ("edit-demo", "calculator", "Video Pacing Calculator"),
    ("alt-hosting", "research_brief", "Non-GCP Hosting Comparison"),
    ("goal-graph-view", "mini_app", "Agent Execution State UI Simulator"),
]

JOURNAL = [
    ("interviewer", "question", "What would prove to a judge that this launched?"),
    ("interviewer", "answer", "A deployed URL plus a 4-minute Devpost video."),
    ("Interviewer", "decision", "Charter locked: deployed URL + 4-minute video by Aug 31."),
    ("Cartographer", "decision", "Graph drawn: 11 nodes, three parallel roots."),
    ("Toolwright", "build", "Built checklist 'Backend Verification Checklist' (passed)"),
    ("Toolwright", "build", "Built script '4-Minute Demo Script Template' (passed)"),
    ("derek", "insight", "Cloud Run needs billing enabled and nobody has GCP admin."),
    ("coach", "blocker", "Deployment blocked on GCP billing; routing via Vercel."),
    ("Referee", "decision", "Node 'verify-agent-backend' closed. Evidence: curl logs, 3x 200 OK."),
]


def main() -> None:
    cid = store.create_challenge(
        {
            "title": "Launch MicroGoals at the hackathon",
            "outcome": "A deployed URL where a judge types a goal and watches agents "
                       "build them a working tool, plus a 4-minute Devpost video.",
            "definition_of_done": "Submitted on Devpost before Aug 31, 5pm PDT.",
            "deadline": "2026-08-31",
            "constraints": ["3 hours a night on weekdays", "solo", "never used ADK"],
            "prior_attempts": ["Ran out of time on the video at the last two hackathons"],
            "stakeholders": ["Derek", "Dana"],
        },
        owner_id="derek", group_id="grp_team",
    )

    for nid, title, deps, status, mins in NODES:
        store.put_node(cid, {
            "id": nid, "title": title, "description": title,
            "acceptance_criteria": f"{title} is finished and verifiable by a third party.",
            "depends_on": deps, "effort_mins": mins, "status": status,
        })
    store.set_node_status(cid, "verify-agent-backend", "done",
                          "curl logs for 3 sample goals, all 200 OK")
    store.set_node_status(cid, "demo-video-script", "done", "script.md committed")

    for node_id, ttype, name in TOOLS:
        store.put_tool(cid, node_id, {
            "type": ttype, "name": name, "source": "# generated",
            "usage": "Open it and work through it top to bottom.",
            "smoke_test_passed": True, "degraded": False,
        })

    for actor, kind, text in JOURNAL:
        store.add_journal(cid, {"actor": actor, "kind": kind, "text": text})

    store.add_group_fact("grp_team",
                         "Cloud Run needs billing enabled and nobody on the team has "
                         "GCP admin, so hosting goes through Vercel.")
    store.add_group_fact("grp_team",
                         "Devpost rejects videos over 4 minutes; target 3:45.")
    store.add_feedback(cid, {"target_type": "tool", "target_id": "spike",
                             "verdict": "up", "reason": "Caught the auth step."})

    print(f"seeded challenge {cid}")
    print(f"  nodes   : {len(store.list_nodes(cid))}")
    print(f"  tools   : {len(store.list_tools(cid))}")
    print(f"  journal : {len(store.list_journal(cid))}")
    print(f"\nopen  http://localhost:8080/app?id={cid}")


if __name__ == "__main__":
    main()
