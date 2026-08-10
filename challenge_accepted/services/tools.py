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

from .store import store

PENDING_JOURNAL = "journal.pending"


def _challenge_id(tool_context: ToolContext) -> Optional[str]:
    """Current challenge id, or None if the charter has not been saved yet."""
    cid = tool_context.state.get("challenge_id")
    return str(cid) if cid else None


def _group_id(tool_context: ToolContext) -> str:
    gid = tool_context.state.get("group_id")
    if gid:
        return str(gid)
    return f"grp_{tool_context.state.get('user_id', 'anon')}"


def save_charter(
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

    # Flush anything the Interviewer journalled before the charter existed.
    for entry in tool_context.state.get(PENDING_JOURNAL) or []:
        store.add_journal(cid, entry)
    tool_context.state[PENDING_JOURNAL] = []

    store.add_journal(cid, {"actor": "Interviewer", "kind": "decision",
                            "text": f"Charter locked: {outcome}"})
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
    tool_context.state["node_ids"] = [n.get("id") for n in nodes]
    store.add_journal(cid, {"actor": "Cartographer", "kind": "decision",
                            "text": f"Graph drawn: {len(nodes)} nodes. {rationale}"})
    return {"status": "ok", "node_count": len(nodes)}


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
    store.add_group_fact(_group_id(tool_context), fact)
    cid = _challenge_id(tool_context)
    if cid:
        store.add_journal(cid, {"actor": "Archivist", "kind": "insight", "text": fact})
    return {"status": "ok"}


def read_challenge_state(tool_context: ToolContext) -> dict[str, Any]:
    """Read the current challenge: charter, all nodes with status, and group facts.

    Safe to call before anything exists. When there is no challenge yet the status is
    "no_challenge" and you should simply begin the interview from scratch -- group
    facts are still returned, because the user may have history from other challenges.

    Returns:
        A dict with status, charter, nodes, tools and group_facts.
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
    return {
        "status": "ok",
        "challenge_id": cid,
        "charter": challenge.get("charter", {}),
        "nodes": store.list_nodes(cid),
        "tools": [{"node_id": t.get("node_id"), "name": t.get("name"), "type": t.get("type")}
                  for t in store.list_tools(cid)],
        "group_facts": group_facts,
    }


def complete_node(node_id: str, evidence: str, tool_context: ToolContext) -> dict[str, Any]:
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
    return {"status": "ok"}


#: Grouped for convenient wiring in sub_agents/*.
WRITE_TOOLS = [write_journal, remember_group_fact]
READ_TOOLS = [read_challenge_state]
