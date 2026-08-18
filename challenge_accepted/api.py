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

import json
import secrets
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .authgate import current
from .services import auth
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


class JoinIn(BaseModel):
    user_id: str = Field(
        description="Who the browser says it is. IGNORED when auth is required -- the "
                    "roster is built from the verified token, because honouring a "
                    "client's claim here would let anyone add anyone to any party. "
                    "Still load-bearing with auth off, e.g. a local dev server.")
    token: str = Field(
        default="",
        description="The secret half of the invite link (`?k=`). Required to join a "
                    "challenge you are not already on. Not required to re-announce "
                    "yourself if you are already a member -- otherwise rotating the "
                    "link would lock out the people it was rotated to protect.")


#: Bytes of JSON a single tool may save per person. Generous for a season of training
#: logs, small enough that a runaway loop in model-written JavaScript cannot turn this
#: into a storage bill.
TOOL_STATE_LIMIT = 64 * 1024


class ToolStateIn(BaseModel):
    state: dict[str, Any] = Field(
        default_factory=dict,
        description="Whatever the tool wants to remember for this person. Opaque to "
                    "the server -- it is the tool's own shape, not ours.")


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


def _members(challenge: dict[str, Any]) -> list[str]:
    group = store.get("groups", str(challenge.get("group_id") or "")) or {}
    return [str(m) for m in (group.get("members") or [])]


def _mine(challenge_id: str, caller: auth.Caller) -> dict[str, Any]:
    """The challenge, if this caller is on its party.

    Membership -- not possession of the id -- is what grants access. An invite link is
    an invitation to JOIN, and joining is a separate, deliberate act (`POST .../join`).
    Before this, any id that leaked in a screenshot or a shared URL handed over
    somebody's whole plan, their journal and the tools built for them.

    With CA_AUTH off there is no caller to check, so this degrades to the old
    behaviour. That is the honest meaning of "auth off", and /healthz reports it.
    """
    challenge = _challenge_or_404(challenge_id)
    if not auth.required():
        return challenge
    if caller.uid == str(challenge.get("owner_id") or ""):
        return challenge
    if caller.uid in _members(challenge):
        return challenge
    # 403 rather than 404: pretending it does not exist would be a lie the UI cannot
    # act on, and the id was already known to whoever asked.
    raise HTTPException(
        status_code=403,
        detail="You have not joined this quest yet. Open the invite link and join.")


def _party(challenge: dict[str, Any]) -> list[dict[str, str]]:
    """The roster as people rather than ids.

    `u_9a3d0a, trace_55eb8a45` was what a teammate actually saw in the Party pane.
    Profiles are written on join from the verified token, so a name here was proved by
    Google rather than typed into a box.
    """
    out = []
    for uid in _members(challenge):
        profile = store.get("users", uid) or {}
        out.append({
            "id": uid,
            "name": str(profile.get("name") or uid[:8]),
            "picture": str(profile.get("picture") or ""),
        })
    return out


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
        "vertex": config.use_memory_bank(),
        "memory": "agentengine" if config.use_memory_bank() else "none",
        "sessions": "agentengine" if config.use_vertex_sessions() else "firestore",
        # Whether the door is locked, stated where anyone can read it without a token.
        # This lives on /api/healthz as well as /healthz because /api/healthz is the
        # one that actually resolves in production -- ADK's static mount shadows bare
        # paths, which is the trap already documented above.
        "auth": auth.AUTH_MODE,
        "auth_configured": auth.browser_config()["enabled"],
        "models": {
            "reasoning": config.MODEL_REASONING,
            "cheap": config.MODEL_CHEAP,
        },
    }


@router.get("/auth/config")
def auth_config() -> dict[str, Any]:
    """What the browser needs to start a Google sign-in, and nothing else.

    Public by design -- the Firebase API key identifies the project, it does not
    authorise anything, and the browser cannot sign in without knowing which project
    to sign in to. Served from the environment rather than baked into app.html so a
    fork does not ship our project id.
    """
    return auth.browser_config()


@router.get("/me")
def me(caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Who the server thinks you are. The UI renders this, so a wrong answer is loud.

    It also writes the profile, which is not decoration. Profiles were only ever
    written on `POST .../join`, and the person who STARTS a quest never joins it --
    `save_charter` puts them on the roster server-side and the browser is told not to
    auto-join under auth. So the owner had no user document, `_party()` fell back to
    `uid[:8]`, and the founder of a quest appeared on their own party roster as eight
    characters of their user id while everyone who arrived by invite link had a name
    and an avatar. It is the one screen the collaborative claim rests on.

    Conditional: a read and a compare before any write, so this does not become a
    Firestore write on every page load. `put_user` merges, so a thinner token later
    cannot blank a name.
    """
    if auth.required() and caller.uid:
        known = store.get("users", caller.uid) or {}
        fresh = {"name": caller.display, "email": caller.email, "picture": caller.picture}
        if any(v and known.get(k) != v for k, v in fresh.items()):
            store.put_user(caller.uid, fresh)
    return {"uid": caller.uid, "name": caller.display, "email": caller.email,
            "picture": caller.picture, "auth": auth.AUTH_MODE}


@router.get("/challenges")
def list_challenges(
    group_id: Optional[str] = None,
    limit: int = 50,
    counts: bool = False,
    caller: auth.Caller = Depends(current),
) -> dict[str, Any]:
    """Challenges, newest first. This fills the quest picker.

    `counts` is OFF by default, and that is the whole point. This endpoint used to
    compute a node count for every challenge unconditionally -- one Firestore query
    each -- for a number the picker never rendered. Measured with 25 challenges in the
    store and a single idle browser, that was 81 node queries in 12 seconds, and it grew
    linearly with every quest any previous visitor had ever created.
    `scripts\\check_poll_cost.py` fails the build if it comes back.
    """
    # The picker is not a directory of everyone's goals. Before auth it listed every
    # challenge in the store, so a new visitor's first screen was a dropdown of
    # strangers' plans -- and that was also the reason the poll-cost bug hurt.
    if auth.required():
        rows = [c for c in store.list_challenges(None)
                if caller.uid == str(c.get("owner_id") or "")
                or caller.uid in _members(c)][:max(0, limit)]
    else:
        rows = store.list_challenges(group_id)[:max(0, limit)]
    out = []
    for c in rows:
        row = {
            "id": c.get("id"),
            "title": (c.get("charter") or {}).get("title") or "Untitled challenge",
            "outcome": (c.get("charter") or {}).get("outcome", ""),
            "group_id": c.get("group_id"),
            "created_at": c.get("created_at"),
        }
        if counts:
            row["nodes"] = len([
                n for n in store.list_nodes(str(c.get("id")))
                if n.get("status") != "superseded"
            ])
        out.append(row)
    return {"challenges": out}


@router.get("/challenges/{challenge_id}")
def get_challenge(challenge_id: str,
                  caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Everything the UI needs for one challenge, in a single round trip."""
    challenge = _mine(challenge_id, caller)
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
        # Who else is on this. The UI shows the count so a second browser joining is
        # visible without waiting for that teammate to discover something.
        "party": _party(challenge),
    }


@router.post("/challenges/{challenge_id}/join")
def join_challenge(challenge_id: str, body: JoinIn,
                   caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Put the caller on this challenge's party roster.

    Joining is a UI act, not an agent decision. The first version relied on the model
    calling a tool that happened to resolve the group -- so a teammate who opened the
    invite link and read for five minutes was invisible to everyone else, and if the
    model chose not to call a tool at all they were never on the roster. A judge
    watching two browsers would have seen "1 in party" on both. Deterministic beats
    clever: the browser says who it is on load, and the roster is right immediately.
    """
    # The ONE route that is authenticated but not membership-gated -- joining is how
    # you become a member, so gating it on membership would lock the door from the
    # inside. `body.user_id` is ignored once auth is on: it is a client claim, and
    # honouring it would let anyone add anyone to any party.
    challenge = _challenge_or_404(challenge_id)
    group_id = str(challenge.get("group_id") or "")
    if not group_id:
        raise HTTPException(status_code=409, detail="Challenge has no group")
    uid = caller.uid if auth.required() else body.user_id

    # The link has a secret half now, and this is where it earns its keep. Without it
    # the id alone was the credential: forward the link once and that is access to
    # somebody's plan forever, with eviction-after-you-notice as the only remedy.
    #
    # Members skip the check. Rotating a link is something you do BECAUSE it leaked,
    # and locking out the people it was rotated to protect would make the button
    # unusable at the moment it matters.
    already = uid in _members(challenge) or uid == str(challenge.get("owner_id") or "")
    if auth.required() and not already:
        expected = str(challenge.get("invite_token") or "")
        if not expected or not secrets.compare_digest(body.token or "", expected):
            raise HTTPException(
                status_code=403,
                detail="This invite link is no longer valid. Ask whoever sent it for "
                       "a fresh one -- links can be reset, and old ones stop working.")

    if auth.required():
        # Written on every join so a name change in the Google account shows up, and
        # so the roster can render people without a second lookup service.
        store.put_user(uid, {"name": caller.display, "email": caller.email,
                             "picture": caller.picture})
    store.join_group(group_id, uid)
    return {"status": "ok", "group_id": group_id, "party": _party(challenge)}


@router.get("/challenges/{challenge_id}/invite")
def get_invite(challenge_id: str,
               caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """The current invite secret, for anyone already on the party.

    Members, not just the owner: a teammate pulling in a third person is the ordinary
    way a party grows, and making them route it through the founder would be a
    workflow rule pretending to be a security one. Anyone who can read the plan can
    already copy it out; what the token controls is who gets a live seat.
    """
    _mine(challenge_id, caller)
    return {"challenge_id": challenge_id, "token": store.invite_token(challenge_id)}


@router.post("/challenges/{challenge_id}/invite/rotate")
def rotate_invite(challenge_id: str,
                  caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Kill every invite link ever sent for this challenge. Owner only.

    Owner only, unlike reading it. Reading the token lets you grow the party; rotating
    it takes a capability away from everyone the owner has already handed it to, and
    that is the founder's call. Nobody currently on the roster is affected -- they are
    members, and members do not need the link.
    """
    challenge = _challenge_or_404(challenge_id)
    if auth.required() and caller.uid != str(challenge.get("owner_id") or ""):
        raise HTTPException(
            status_code=403,
            detail="Only the person who started this quest can reset its invite link.")
    return {"challenge_id": challenge_id,
            "token": store.invite_token(challenge_id, rotate=True)}


@router.delete("/challenges/{challenge_id}/party/{user_id}")
def remove_from_party(challenge_id: str, user_id: str,
                      caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Take somebody off the party. Yourself always; anyone else only if you own it.

    A door with no handle on the inside is not a door. Until this route existed the
    party was append-only: anyone holding an invite link could join, nobody could
    leave, and nobody could be removed -- so a link forwarded once was permanent
    access to somebody's plan, their journal and their tools. That is a worse failure
    than the one the membership wall was built to fix, because it is silent.

    Two rules, and no third:

      * you may always remove YOURSELF -- leaving is not something you ask permission
        for, and the alternative is a product that can trap you in a stranger's party;
      * the OWNER may remove anyone else. Not "any member": a teammate who could evict
        the person whose goal it is would be a takeover, and on a party you join by
        link that is not hypothetical.

    The owner cannot be removed at all, including by themselves. Their user id is on
    the challenge document, so an ownerless challenge is not a state the rest of this
    file knows how to render.
    """
    challenge = _challenge_or_404(challenge_id)
    group_id = str(challenge.get("group_id") or "")
    if not group_id:
        raise HTTPException(status_code=409, detail="Challenge has no group")

    owner = str(challenge.get("owner_id") or "")
    if auth.required():
        if user_id != caller.uid and caller.uid != owner:
            raise HTTPException(
                status_code=403,
                detail="Only the person who started this quest can remove someone else.")
        if caller.uid != owner and caller.uid not in _members(challenge):
            raise HTTPException(status_code=403, detail="You are not on this party.")
    if user_id == owner:
        raise HTTPException(
            status_code=409,
            detail="The person who started this quest cannot be removed from it.")

    before = _members(challenge)
    store.leave_group(group_id, user_id)
    return {
        "status": "ok" if user_id in before else "not_a_member",
        "removed": user_id,
        "left": user_id == (caller.uid if auth.required() else user_id),
        "party": _party(challenge),
    }


@router.get("/challenges/{challenge_id}/tools/{tool_id}/state")
def get_tool_state(challenge_id: str, tool_id: str,
                   caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """What this tool has saved for you.

    The page that needs this cannot ask for it. Tools run in a sandboxed iframe with
    no same-origin privilege -- no storage, no cookies, no way to attach a token -- so
    the dashboard fetches on the tool's behalf and hands the state in. The tool never
    sees a credential, which is the entire reason the sandbox is that tight: the
    source running in there was written by a model.
    """
    _mine(challenge_id, caller)
    return {"tool_id": tool_id, "state": store.get_tool_state(tool_id, caller.uid)}


@router.put("/challenges/{challenge_id}/tools/{tool_id}/state")
def put_tool_state(challenge_id: str, tool_id: str, body: ToolStateIn,
                   caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Save what this tool has recorded for you.

    Bounded on purpose. This is a key-value bag written by model-generated JavaScript
    running in a loop nobody reviewed, and an unbounded one is a free write endpoint
    on somebody else's Firestore bill. A tracker logging a season of runs is a few
    kilobytes; anything past the cap is a bug in the tool, and it is told so rather
    than silently truncated.
    """
    _mine(challenge_id, caller)
    if not any(t.get("id") == tool_id for t in store.list_tools(challenge_id)):
        raise HTTPException(status_code=404, detail="No such tool on this challenge")
    size = len(json.dumps(body.state))
    if size > TOOL_STATE_LIMIT:
        raise HTTPException(
            status_code=413,
            detail=f"Tool state is {size} bytes; the limit is {TOOL_STATE_LIMIT}.")
    store.put_tool_state(challenge_id, tool_id, caller.uid, body.state)
    return {"status": "ok", "bytes": size}


@router.get("/challenges/{challenge_id}/graph")
def get_graph(challenge_id: str, include_superseded: bool = False,
              caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """React Flow nodes and edges, laid out by dependency depth."""
    _mine(challenge_id, caller)
    return _build_graph(store.list_nodes(challenge_id),
                        store.list_tools(challenge_id),
                        include_superseded)


def _build_graph(raw: list[dict[str, Any]], all_tools: list[dict[str, Any]],
                 include_superseded: bool = False) -> dict[str, Any]:
    """Layout from ALREADY-FETCHED rows.

    Split out so `/dashboard` can build the graph from the same nodes and tools it
    already read for the summary, instead of querying them a second time.
    """
    if not include_superseded:
        raw = [n for n in raw if n.get("status") != "superseded"]
    by_id = {n["id"]: n for n in raw}

    tools_by_node: dict[str, list[dict[str, Any]]] = {}
    for tool in all_tools:
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
def get_journal(challenge_id: str, limit: int = 100,
                caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """The 'takes notes' surface. Newest last, so the UI can append and autoscroll."""
    _mine(challenge_id, caller)
    # One read. This used to call list_journal twice -- once for the window, once to
    # count -- which is two Firestore queries for a number you already have.
    entries = store.list_journal(challenge_id)
    return {"entries": entries[-limit:], "total": len(entries)}


@router.get("/challenges/{challenge_id}/dashboard")
def get_dashboard(challenge_id: str, journal_limit: int = 100,
                  caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Everything the dashboard polls for, in ONE round trip.

    The UI needs the summary, the graph, the journal and the tools together, and it
    asks every 1.2s during a run. Fetching them as four requests meant four separate
    `_challenge_or_404` reads and a second pass over nodes and tools -- twelve Firestore
    reads per poll where five will do, plus four round trips of latency on every frame
    of the one animation this product is judged on.

    The four endpoints stay: they are a clearer API to read, and the checks use them.
    This is what the browser uses.
    """
    challenge = _mine(challenge_id, caller)
    group = store.get("groups", str(challenge.get("group_id", ""))) or {}
    nodes = store.list_nodes(challenge_id)
    tools = store.list_tools(challenge_id)
    journal = store.list_journal(challenge_id)
    live = [n for n in nodes if n.get("status") != "superseded"]

    return {
        "summary": {
            "id": challenge_id,
            "charter": challenge.get("charter", {}),
            "status": challenge.get("status"),
            "owner_id": challenge.get("owner_id"),
            "group_id": challenge.get("group_id"),
            "counts": {
                "nodes": len(live),
                "done": len([n for n in live if n.get("status") == "done"]),
                "tools": len(tools),
            },
            "group_facts": group.get("shared_facts", []),
            "party": _party(challenge),
        },
        "graph": _build_graph(nodes, tools),
        "journal": {"entries": journal[-journal_limit:], "total": len(journal)},
        "tools": {"tools": tools},
    }


@router.get("/challenges/{challenge_id}/tools")
def get_tools(challenge_id: str,
              caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    _mine(challenge_id, caller)
    return {"tools": store.list_tools(challenge_id)}


@router.get("/challenges/{challenge_id}/feedback")
def get_feedback(challenge_id: str,
                 caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    _mine(challenge_id, caller)
    return {"feedback": store.list_feedback(challenge_id)}


@router.post("/challenges/{challenge_id}/feedback", status_code=201)
def post_feedback(challenge_id: str, body: FeedbackIn,
                  caller: auth.Caller = Depends(current)) -> dict[str, Any]:
    """Thumbs up/down straight from the UI, without going through an agent turn.

    The track brief asks for "a clear way to capture feedback". A button that writes
    directly is clearer than hoping the user phrases it so the Coach notices.
    """
    _mine(challenge_id, caller)
    if body.verdict not in ("up", "down"):
        raise HTTPException(status_code=422, detail="verdict must be 'up' or 'down'")
    fid = store.add_feedback(challenge_id, body.model_dump())
    return {"status": "ok", "feedback_id": fid}
