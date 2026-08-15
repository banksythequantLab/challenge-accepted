"""ADK FunctionTools that agents call to read and write the shared data source.

Every one of these writes to Firestore (or the local stub) rather than to session
state, so parallel branches and other teammates see the same truth.

DESIGN RULE, learned the hard way: a tool must never raise for a condition the model
could legitimately produce. An exception inside a tool propagates up through the ADK
node runner and kills the whole invocation -- one over-eager `read_challenge_state`
before the charter existed took down an entire run. Tools return a status dict instead,
and the model reads the status and adapts.
"""

from __future__ import annotations

from typing import Any, Optional

from google.adk.tools import ToolContext

from . import memory
from .store import store

PENDING_JOURNAL = "journal.pending"
JOINED_GROUP = "joined_group"


def _challenge_id(tool_context: ToolContext) -> Optional[str]:
    """Current challenge id, or None if the charter has not been saved yet."""
    cid = tool_context.state.get("challenge_id")
    return str(cid) if cid else None


def _join_party(tool_context: ToolContext, group_id: str) -> None:
    """Add the user to the group roster, at most once per session.

    Guarded by a state flag because _group_id runs on every tool call and this is a
    Firestore write. One write when a teammate first touches the challenge, none
    after that.
    """
    if tool_context.state.get(JOINED_GROUP) == group_id:
        return
    store.join_group(group_id, str(tool_context.state.get("user_id", "anon")))
    tool_context.state[JOINED_GROUP] = group_id


def _group_id(tool_context: ToolContext) -> str:
    """The party this work belongs to.

    The challenge document is the source of truth, NOT session state. A teammate
    who opens /app?id=<cid> arrives carrying a group_id minted from their own
    localStorage, which will never match the group that owns the challenge. If we
    trusted that, every discovery they made would be filed under a party of one and
    `read_challenge_state` would hand them an empty group_facts list -- the exact
    opposite of the feature. So resolve through the challenge whenever there is one,
    and fall back to state only before a charter exists.
    """
    cid = tool_context.state.get("challenge_id")
    if cid:
        owner_group = (store.get("challenges", str(cid)) or {}).get("group_id")
        if owner_group:
            # Write it back so anything reading state directly agrees with us.
            tool_context.state["group_id"] = str(owner_group)
            _join_party(tool_context, str(owner_group))
            return str(owner_group)
    gid = tool_context.state.get("group_id")
    if gid:
        return str(gid)
    return f"grp_{tool_context.state.get('user_id', 'anon')}"


#: Things people write when they mean "nothing here". Recording "None (running solo)"
#: as a shared discovery makes the party notebook look like a form dump.
_EMPTY_ANSWERS = {"", "none", "n/a", "na", "nothing", "no", "unknown", "not applicable",
                  "none stated", "none given", "none specified", "-"}


def _is_empty_answer(text: str) -> bool:
    stripped = text.strip().strip(".").lower()
    return not stripped or stripped in _EMPTY_ANSWERS or stripped.startswith("none (")


def _charter_facts(charter: dict[str, Any]) -> list[str]:
    """The parts of a charter a teammate would otherwise have to ask about.

    Deliberately NOT the title or the outcome: those are already the headline on every
    screen, and repeating them in the party notebook is padding, not intelligence.
    """
    facts: list[str] = []
    deadline = str(charter.get("deadline") or "").strip()
    if deadline and not _is_empty_answer(deadline):
        facts.append(f"Deadline: {deadline}.")
    for c in charter.get("constraints") or []:
        if isinstance(c, str) and not _is_empty_answer(c):
            facts.append(c.strip())
    for a in charter.get("prior_attempts") or []:
        if isinstance(a, str) and not _is_empty_answer(a):
            facts.append(f"Already tried: {a.strip()}")
    for s in charter.get("stakeholders") or []:
        if isinstance(s, str) and not _is_empty_answer(s):
            facts.append(f"Also involved: {s.strip()}")
    return facts


async def save_charter(
    title: str,
    outcome: str,
    definition_of_done: str,
    deadline: str,
    constraints: list[str],
    prior_attempts: list[str],
    stakeholders: list[str],
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Persist the completed challenge charter and open the challenge.

    Call this exactly once, at the end of the ACCEPT phase, when you can fill every
    field honestly. Do not call it with placeholder text.

    Args:
        title: Short name for the challenge, in the user's own words.
        outcome: The specific end state, observable by a third party.
        definition_of_done: How we will know it is finished.
        deadline: ISO date or the relative phrase the user gave. Empty string if none.
        constraints: Time, money, skill, access and energy limits the user stated.
        prior_attempts: What the user already tried and why it did not work.
        stakeholders: Other people involved in this challenge.

    Returns:
        A dict with status and the new challenge_id.
    """
    charter = {
        "title": title,
        "outcome": outcome,
        "definition_of_done": definition_of_done,
        "deadline": deadline,
        "constraints": constraints,
        "prior_attempts": prior_attempts,
        "stakeholders": stakeholders,
    }
    user_id = str(tool_context.state.get("user_id", "anon"))
    group_id = _group_id(tool_context)
    cid = store.create_challenge(charter, owner_id=user_id, group_id=group_id)

    tool_context.state["challenge_id"] = cid
    tool_context.state["group_id"] = group_id
    tool_context.state["charter"] = charter
    # The founder is party member #1, so the roster is never empty for a live challenge.
    store.join_group(group_id, user_id)
    tool_context.state[JOINED_GROUP] = group_id

    # Flush anything the Interviewer journalled before the charter existed.
    for entry in tool_context.state.get(PENDING_JOURNAL) or []:
        store.add_journal(cid, entry)
    tool_context.state[PENDING_JOURNAL] = []

    store.add_journal(cid, {"actor": "Interviewer", "kind": "decision",
                            "text": f"Charter locked: {outcome}"})

    # Seed the party's shared notebook from the interview.
    #
    # `remember_group_fact` only fires on a RETURNING turn -- someone coming back and
    # saying something new. So on a fresh challenge the Party pane read "Nothing
    # learned yet" at the exact moment a teammate opened the invite link, even though
    # the interview had just established the deadline, the constraints and everything
    # already tried. The densest facts in the whole run were sitting in the charter
    # where the Party pane does not look.
    #
    # Done in code rather than by asking an agent to do it: these facts are already
    # known and structured, and a prompt that says "now also record these" is a prompt
    # that can claim it did and not have.
    shared = 0
    for fact in _charter_facts(charter):
        if store.add_group_fact(group_id, fact):
            shared += 1
    if shared:
        store.add_journal(cid, {
            "actor": "Interviewer", "kind": "insight",
            "text": f"Shared {shared} fact{'s' if shared != 1 else ''} from the "
                    f"interview with the party."})

    # The interview is the densest source of durable facts about this person -- what
    # they tried before, what they are short of, who else is involved. Hand it to
    # Memory Bank here, while it is still in the session, so the *next* challenge
    # starts from what we already learned. Never fatal; see services/memory.py.
    await memory.remember_session(tool_context)
    return {"status": "ok", "challenge_id": cid}


def save_goal_graph(nodes: list[dict], rationale: str,
                    tool_context: ToolContext) -> dict[str, Any]:
    """Persist the goal graph produced in the MAP phase.

    Args:
        nodes: List of node dicts, each with keys: id, title, description,
            acceptance_criteria, depends_on (list of node ids), effort_mins.
        rationale: Two sentences on why the graph is shaped this way.

    Returns:
        A dict with status and the count of nodes written.
    """
    cid = _challenge_id(tool_context)
    if not cid:
        return {"status": "no_challenge",
                "message": "No charter saved yet. The ACCEPT phase must finish first."}
    for node in nodes:
        store.put_node(cid, node)

    # Redrawing must REPLACE the plan, not append to it. A live re-plan after a blocker
    # produced 24 nodes -- the old graph and the new one side by side. Nodes already
    # done keep their status and evidence; the rest are marked superseded.
    keep = [n.get("id") for n in nodes]
    retired = store.supersede_nodes(cid, keep)

    tool_context.state["node_ids"] = keep
    store.add_journal(cid, {"actor": "Cartographer", "kind": "decision",
                            "text": f"Graph drawn: {len(nodes)} nodes"
                                    + (f", {retired} superseded" if retired else "")
                                    + f". {rationale}"})
    return {"status": "ok", "node_count": len(nodes), "superseded": retired}


def save_tool(node_id: str, tool_type: str, name: str, source: str, usage: str,
              smoke_test_passed: bool, smoke_test_output: str,
              tool_context: ToolContext) -> dict[str, Any]:
    """Attach a built tool to a node at the end of the FORGE phase.

    Args:
        node_id: The goal-graph node this tool serves.
        tool_type: One of calculator, checklist, research_brief, drill, tracker,
            script, mini_app.
        name: Short human-readable name for the tool.
        source: The tool itself -- Python source, JSON, or self-contained HTML.
        usage: One paragraph telling the user how to use it.
        smoke_test_passed: Whether your own smoke test passed. Be truthful.
        smoke_test_output: What the smoke test actually printed.

    Returns:
        A dict with status and the new tool_id.
    """
    cid = _challenge_id(tool_context)
    if not cid:
        return {"status": "no_challenge", "message": "No challenge open."}
    tid = store.put_tool(cid, node_id, {
        "type": tool_type, "name": name, "source": source, "usage": usage,
        "smoke_test_passed": smoke_test_passed, "smoke_test_output": smoke_test_output,
        "degraded": not smoke_test_passed,
    })
    store.add_journal(cid, {"actor": "Toolwright", "kind": "build", "node_id": node_id,
                            "text": f"Built {tool_type} '{name}' "
                                    f"({'passed' if smoke_test_passed else 'DEGRADED'})"})
    return {"status": "ok", "tool_id": tid}


def write_journal(kind: str, text: str, actor: str, node_id: str,
                  tool_context: ToolContext) -> dict[str, Any]:
    """Write one visible note to the challenge journal.

    Safe to call at any time, including before a charter exists -- early notes are
    buffered and flushed the moment the charter is saved.

    Args:
        kind: One of decision, question, answer, insight, blocker, build.
        text: The note, one sentence.
        actor: Your agent name.
        node_id: Related node id, or empty string if not node-specific.

    Returns:
        A status dict.
    """
    entry = {"actor": actor, "kind": kind, "text": text, "node_id": node_id or None}
    cid = _challenge_id(tool_context)
    if not cid:
        pending = list(tool_context.state.get(PENDING_JOURNAL) or [])
        pending.append(entry)
        tool_context.state[PENDING_JOURNAL] = pending
        return {"status": "buffered", "pending": len(pending)}
    return {"status": "ok", "entry_id": store.add_journal(cid, entry)}


def record_feedback(target_type: str, target_id: str, verdict: str, reason: str,
                    tool_context: ToolContext) -> dict[str, Any]:
    """Record the user's thumbs up/down and their reason.

    Args:
        target_type: One of node, tool, question, graph.
        target_id: Id of the thing being rated.
        verdict: "up" or "down".
        reason: The user's stated reason, in their words.

    Returns:
        A status dict.
    """
    cid = _challenge_id(tool_context)
    if not cid:
        return {"status": "no_challenge", "message": "No challenge open."}
    fid = store.add_feedback(cid, {"target_type": target_type, "target_id": target_id,
                                   "verdict": verdict, "reason": reason})
    return {"status": "ok", "feedback_id": fid}


def remember_group_fact(fact: str, tool_context: ToolContext) -> dict[str, Any]:
    """Save a fact that everyone working on this challenge should know.

    This is the group-intelligence primitive. Use it for anything a teammate would
    otherwise have to rediscover -- an office that only takes Tuesday appointments,
    a vendor that never replies, a constraint the owner mentioned in passing.

    Args:
        fact: One sentence, stated as a durable fact rather than a moment in time.

    Returns:
        A status dict.
    """
    stored = store.add_group_fact(_group_id(tool_context), fact)
    cid = _challenge_id(tool_context)
    if cid and stored:
        # Attribute to the PERSON, not to the agent that happened to write it. Logging
        # "Archivist" here meant a teammate's Coach had no way to say "Derek found..."
        # -- it fell back to "the team found...", which reads like a database, not a
        # shared workspace. The journal actor is the attribution source.
        store.add_journal(cid, {
            "actor": str(tool_context.state.get("user_id", "someone on the team")),
            "kind": "insight",
            "text": fact,
        })
    return {"status": "ok", "stored": stored,
            "note": "" if stored else "Already known to the group; not duplicated."}


def read_challenge_state(tool_context: ToolContext) -> dict[str, Any]:
    """Read the current challenge: charter, all nodes with status, and group facts.

    Safe to call before anything exists. When there is no challenge yet the status is
    "no_challenge" and you should simply begin the interview from scratch -- group
    facts are still returned, because the user may have history from other challenges.

    `recent_journal` is included so you can attribute a group fact to the teammate who
    actually hit it ("Derek found...") rather than stating it anonymously.

    `tool_feedback` carries the user's thumbs up/down on tools already built, with
    their reason and the node it belongs to. Thumbs-down entries come first. Read it
    before building anything for a node that already has a rejected tool.

    Returns:
        A dict with status, charter, nodes, tools, group_facts, recent_journal and
        tool_feedback.
    """
    group_facts = (store.get("groups", _group_id(tool_context)) or {}).get("shared_facts", [])
    cid = _challenge_id(tool_context)
    if not cid:
        return {
            "status": "no_challenge",
            "message": "No challenge started yet. Begin the interview from scratch.",
            "charter": {},
            "nodes": [],
            "tools": [],
            "group_facts": group_facts,
        }
    challenge = store.get("challenges", cid) or {}
    nodes = store.list_nodes(cid)
    return {
        "status": "ok",
        "challenge_id": cid,
        "charter": challenge.get("charter", {}),
        # Superseded nodes are excluded: they belong to a plan that no longer exists,
        # and handing one to a teammate is the fastest way to look inattentive.
        "nodes": [n for n in nodes if n.get("status") != "superseded"],
        "tools": [{"node_id": t.get("node_id"), "name": t.get("name"), "type": t.get("type")}
                  for t in store.list_tools(cid)],
        "group_facts": group_facts,
        "recent_journal": [
            {"actor": j.get("actor"), "kind": j.get("kind"), "text": j.get("text")}
            for j in store.list_journal(cid)[-12:]
        ],
        "tool_feedback": _tool_feedback(cid),
    }


def _tool_feedback(cid: str) -> list[dict[str, Any]]:
    """What the user actually thought of the tools, resolved to names they'd recognise.

    Feedback used to be write-only. The button wrote a Firestore row and nothing ever
    read it, so "tell it what didn't work and the next one is different" was a promise
    the product did not keep -- the next one was identical. Raw rows are no use to a
    model either: `target_id` is a `tool_...` id, and no agent can reason about that.
    Resolve to node and name, and put the thumbs-down first, because that is the
    feedback that has to change something.
    """
    tools = {t.get("id"): t for t in store.list_tools(cid)}
    out: list[dict[str, Any]] = []
    for fb in store.list_feedback(cid):
        tool = tools.get(fb.get("target_id"), {})
        out.append({
            "target_type": fb.get("target_type"),
            "node_id": tool.get("node_id"),
            "tool_name": tool.get("name"),
            "tool_type": tool.get("type"),
            "verdict": fb.get("verdict"),
            "reason": fb.get("reason") or "",
        })
    out.sort(key=lambda f: f.get("verdict") != "down")
    return out


async def complete_node(node_id: str, evidence: str,
                        tool_context: ToolContext) -> dict[str, Any]:
    """Mark a node done, with the evidence that justifies it.

    Args:
        node_id: The node to close.
        evidence: What the user actually produced or showed. Not "they said so".

    Returns:
        A status dict.
    """
    cid = _challenge_id(tool_context)
    if not cid:
        return {"status": "no_challenge", "message": "No challenge open."}
    store.set_node_status(cid, node_id, "done", evidence)
    store.add_journal(cid, {"actor": "Referee", "kind": "decision", "node_id": node_id,
                            "text": f"Node '{node_id}' closed. Evidence: {evidence}"})

    # A closed node is the other kind of durable fact: not what they said they would
    # do, but what they actually finished and what it took. Never fatal.
    await memory.remember_session(tool_context)
    return {"status": "ok"}


#: Grouped for convenient wiring in sub_agents/*.
WRITE_TOOLS = [write_journal, remember_group_fact]
READ_TOOLS = [read_challenge_state]
