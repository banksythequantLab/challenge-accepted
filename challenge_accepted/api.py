"""Read API for the front end.

The agent side writes through `services.tools`; the UI reads through here. Both hit the
same `store`, so this works against the in-memory backend with zero GCP setup and
against Firestore in production without a code change.

The graph endpoint returns React Flow's exact node/edge shape. Doing that translation
here rather than in the browser keeps the layout rules (rank by depth, colour by status)
in one place, and means the demo UI is a thin renderer -- which is what you want when
you are recording a video at 2am.
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .services.store import store

router = APIRouter(prefix="/api", tags=["challenge"])

#: Colour per node status. Mirrors the architecture diagram's palette.
STATUS_COLOR = {
    "todo": "#5F6368",
    "active": "#4285F4",
    "blocked": "#EA4335",
    "done": "#34A853",
    "superseded": "#DADCE0",
}


class FeedbackIn(BaseModel):
    target_type: str = Field(description="node | tool | question | graph")
    target_id: str
    verdict: str = Field(description="up | down")
    reason: str = ""


def _challenge_or_404(challenge_id: str) -> dict[str, Any]:
    challenge = store.get("challenges", challenge_id)
    if not challenge:
        raise HTTPException(status_code=404, detail=f"No challenge {challenge_id}")
    return challenge


def _depth(node_id: str, by_id: dict[str, dict], seen: Optional[set[str]] = None) -> int:
    """Longest path back to a root, used as the graph's column index.

    Guards against cycles. The Cartographer is instructed to emit a DAG, but a model
    can produce a cycle and the UI must not hang because of it.
    """
    seen = seen or set()
    if node_id in seen:
        return 0
    node = by_id.get(node_id)
    if not node:
        return 0
    deps = [d for d in (node.get("depends_on") or []) if d in by_id]
    if not deps:
        return 0
    return 1 + max(_depth(d, by_id, seen | {node_id}) for d in deps)


@router.get("/healthz")
def healthz() -> dict[str, Any]:
    """Health + which storage backend actually engaged.

    Lives on the /api router, not on the app. A `@app.get("/healthz")` added after
    `get_fast_api_app()` returns is registered in the OpenAPI spec but 404s at runtime:
    ADK's web UI mounts static files at "/", and that mount is registered first, so it
    shadows any bare path added afterwards. Routes under a prefixed router are matched
    before the mount, so they work. Verified on the deployed service.

    `store` is the field to read. If it says "memory" on a deployment where
    GOOGLE_CLOUD_PROJECT is set, Firestore silently fell back: no persistence, and each
    Cloud Run instance holds its own private dict.
    """
    from . import config
    from .services.store import store

    return {
        "ok": True,
        "store": store.backend,
        "vertex": config.use_vertex(),
        "models": {
            "reasoning": config.MODEL_REASONING,
            "cheap": config.MODEL_CHEAP,
        },
    }


@router.get("/challenges")
def list_challenges(group_id: Optional[str] = None) -> dict[str, Any]:
    """All challenges, newest first. The UI uses this to pick one with no query string."""
    rows = store.list_challenges(group_id)
    return {
        "challenges": [
            {
                "id": c.get("id"),
                "title": (c.get("charter") or {}).get("title") or "Untitled challenge",
                "outcome": (c.get("charter") or {}).get("outcome", ""),
                "group_id": c.get("group_id"),
                "created_at": c.get("created_at"),
                "nodes": len([
                    n for n in store.list_nodes(str(c.get("id")))
                    if n.get("status") != "superseded"
                ]),
            }
            for c in rows
        ]
    }


@router.get("/challenges/{challenge_id}")
def get_challenge(challenge_id: str) -> dict[str, Any]:
    """Everything the UI needs for one challenge, in a single round trip."""
    challenge = _challenge_or_404(challenge_id)
    group = store.get("groups", str(challenge.get("group_id", ""))) or {}
    nodes = store.list_nodes(challenge_id)
    return {
        "id": challenge_id,
        "charter": challenge.get("charter", {}),
        "status": challenge.get("status"),
        "owner_id": challenge.get("owner_id"),
        "group_id": challenge.get("group_id"),
        "counts": {
            "nodes": len([n for n in nodes if n.get("status") != "superseded"]),
            "done": len([n for n in nodes if n.get("status") == "done"]),
            "tools": len(store.list_tools(challenge_id)),
        },
        "group_facts": group.get("shared_facts", []),
    }


@router.get("/challenges/{challenge_id}/graph")
def get_graph(challenge_id: str, include_superseded: bool = False) -> dict[str, Any]:
    """React Flow nodes and edges, laid out by dependency depth."""
    _challenge_or_404(challenge_id)
    raw = store.list_nodes(challenge_id)
    if not include_superseded:
        raw = [n for n in raw if n.get("status") != "superseded"]
    by_id = {n["id"]: n for n in raw}

    tools_by_node: dict[str, list[dict[str, Any]]] = {}
    for tool in store.list_tools(challenge_id):
        tools_by_node.setdefault(str(tool.get("node_id")), []).append({
            "id": tool.get("id"),
            "name": tool.get("name"),
            "type": tool.get("type"),
            "degraded": bool(tool.get("degraded")),
        })

    column_counts: dict[int, int] = {}
    nodes = []
    for node in sorted(raw, key=lambda n: n["id"]):
        depth = _depth(node["id"], by_id)
        row = column_counts.get(depth, 0)
        column_counts[depth] = row + 1
        status = node.get("status", "todo")
        nodes.append({
            "id": node["id"],
            "position": {"x": depth * 280, "y": row * 140},
            "data": {
                "label": node.get("title") or node["id"],
                "description": node.get("description", ""),
                "acceptance_criteria": node.get("acceptance_criteria", ""),
                "status": status,
                "color": STATUS_COLOR.get(status, "#5F6368"),
                "effort_mins": node.get("effort_mins"),
                "assignee": node.get("assignee_id"),
                "evidence": node.get("evidence", []),
                "tools": tools_by_node.get(node["id"], []),
                "ready": all(
                    by_id.get(d, {}).get("status") == "done"
                    for d in (node.get("depends_on") or [])
                    if d in by_id
                ) and status == "todo",
            },
        })

    edges = [
        {"id": f"{dep}->{node['id']}", "source": dep, "target": node["id"]}
        for node in raw
        for dep in (node.get("depends_on") or [])
        if dep in by_id
    ]
    return {"nodes": nodes, "edges": edges}


@router.get("/challenges/{challenge_id}/journal")
def get_journal(challenge_id: str, limit: int = 100) -> dict[str, Any]:
    """The 'takes notes' surface. Newest last, so the UI can append and autoscroll."""
    _challenge_or_404(challenge_id)
    entries = store.list_journal(challenge_id)[-limit:]
    return {"entries": entries, "total": len(store.list_journal(challenge_id))}


@router.get("/challenges/{challenge_id}/tools")
def get_tools(challenge_id: str) -> dict[str, Any]:
    _challenge_or_404(challenge_id)
    return {"tools": store.list_tools(challenge_id)}


@router.get("/challenges/{challenge_id}/feedback")
def get_feedback(challenge_id: str) -> dict[str, Any]:
    _challenge_or_404(challenge_id)
    return {"feedback": store.list_feedback(challenge_id)}


@router.post("/challenges/{challenge_id}/feedback", status_code=201)
def post_feedback(challenge_id: str, body: FeedbackIn) -> dict[str, Any]:
    """Thumbs up/down straight from the UI, without going through an agent turn.

    The track brief asks for "a clear way to capture feedback". A button that writes
    directly is clearer than hoping the user phrases it so the Coach notices.
    """
    _challenge_or_404(challenge_id)
    if body.verdict not in ("up", "down"):
        raise HTTPException(status_code=422, detail="verdict must be 'up' or 'down'")
    fid = store.add_feedback(challenge_id, body.model_dump())
    return {"status": "ok", "feedback_id": fid}
