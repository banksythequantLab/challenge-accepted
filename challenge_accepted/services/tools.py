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

import json
import os
from typing import Any, Optional

from google.adk.tools import ToolContext

from . import embeddings, memory
from .store import _content_words, store

PENDING_JOURNAL = "journal.pending"
JOINED_GROUP = "joined_group"

#: How many group facts may reach the model in one `read_challenge_state`.
#:
#: This used to be "all of them". Shared memory is the product's centre of gravity, so
#: the list only grows -- and every fact is re-sent on every tool call, on every turn,
#: for every agent that holds this tool. At a few dozen facts that is already a
#: measurable share of a 243k-token challenge, and it degrades in the worst way: the
#: model does not error, it just gets a wall of context and starts missing things in
#: the middle of it. A party that has been working for a month would quietly get worse
#: at remembering than one that started yesterday.
GROUP_FACT_BUDGET = int(os.getenv("CA_GROUP_FACT_BUDGET", "40"))

#: Newest facts are kept regardless of how they score. Relevance ranking is a lexical
#: guess; recency is a fact. The thing a teammate most needs to know is usually what
#: somebody found out an hour ago, and that is exactly what a bag-of-words score
#: against an old charter would rank last.
GROUP_FACT_RECENT = 8


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


#: "Solo runner (no coach or training partners)" is a stakeholder field answered with
#: "there aren't any". Publishing it as a shared discovery to a party of one reads as
#: a form dump. Only applied to stakeholders -- "working alone" is a real constraint.
_SOLO_MARKERS = ("solo", "just me", "myself", "only me", "no one else", "nobody",
                 "no coach", "no team", "no partner", "no other", "alone")


def _is_empty_answer(text: str) -> bool:
    stripped = text.strip().strip(".").lower()
    return not stripped or stripped in _EMPTY_ANSWERS or stripped.startswith("none (")


def _is_nobody(text: str) -> bool:
    low = text.strip().lower()
    return _is_empty_answer(text) or any(m in low for m in _SOLO_MARKERS)


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
        if isinstance(s, str) and not _is_nobody(s):
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

    # A SECOND call updates the quest. It does not mint a rival one.
    #
    # Measured on production: one FORGE run produced two challenges four minutes
    # apart, same title, and the second was empty. The turn had failed mid-flight, the
    # Warden recovered by re-running the ACCEPT phase, and `save_charter` -- which had
    # only ever known how to create -- made a new challenge and pointed session state
    # at it. Everything already built stayed on the first one: twelve nodes, six tools,
    # every journal entry, all orphaned and invisible. The check reported "0 tools
    # built. This is the money shot." and it was wrong about which thing had broken.
    #
    # The instruction says "call this exactly once", and an instruction is not a
    # constraint. Anything a model can do twice, it eventually will -- on a retry,
    # after a crash, or because the user changed their mind halfway through. Losing a
    # challenge's entire contents is a bad outcome for a duplicate function call.
    existing = str(tool_context.state.get("challenge_id") or "")
    if existing and store.get("challenges", existing):
        store._patch("challenges", existing, {"charter": charter})
        store.add_journal(existing, {
            "actor": "Interviewer", "kind": "decision",
            "text": f"Charter updated: {outcome}"})
        tool_context.state["charter"] = charter
        return {"status": "updated", "challenge_id": existing,
                "note": "This challenge already existed, so its charter was updated "
                        "rather than a second one being created. Everything already "
                        "built for it is still attached."}

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


def _spec_is_shared(tool_context: ToolContext, node_id: str) -> bool:
    """Is this node's tool one record for the whole party, or one per person?

    Read off the Quartermaster's spec in session state rather than taken as an argument
    to `save_tool`. A Toolwright would have to echo the flag back correctly on every
    build for an argument to be trustworthy, and a boolean the model can quietly drop
    is a boolean that decides, at random, whether your teammates can see your ledger.
    The spec already carries it and the spec is not written by the worker.

    `tool_specs` can arrive as a dict or as a JSON string depending on the model path
    -- the Dispatcher handles the same two shapes for the same reason.
    """
    raw = tool_context.state.get("tool_specs")
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return False
    specs = (raw or {}).get("specs") if isinstance(raw, dict) else None
    for spec in specs or []:
        if isinstance(spec, dict) and spec.get("node_id") == node_id:
            return bool(spec.get("shared"))
    return False


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
    shared = _spec_is_shared(tool_context, node_id)
    tid = store.put_tool(cid, node_id, {
        "type": tool_type, "name": name, "source": source, "usage": usage,
        "smoke_test_passed": smoke_test_passed, "smoke_test_output": smoke_test_output,
        "degraded": not smoke_test_passed, "shared": shared,
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

    EVERYONE ON THE PARTY READS THIS, INCLUDING PEOPLE WHO HAVE NOT JOINED YET.

    A party grows by invite link. What you write here is shown to the next person who
    arrives, and to the one after that, and it cannot be unsaid -- a teammate leaving
    does not take their facts with them. So the test is not "is this true", it is
    "would the person who told me this expect the whole team to see it".

    Record: constraints, deadlines, things tried and ruled out, how an external party
    actually behaves, a decision and its reason.

    Do NOT record: anything about health, money, relationships, employment or mood
    that the user mentioned to explain themselves rather than to inform the plan.
    "Training four evenings a week" belongs here. "Going through a divorce, which is
    why evenings are hard" does not -- the constraint is the evenings. Strip the
    reason and keep the shape of the work.

    When a fact is only useful to the person who told you, it is not a group fact.
    Say it back to them instead.

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
    gid = _group_id(tool_context)
    all_facts = (store.get("groups", gid) or {}).get("shared_facts", [])
    cid = _challenge_id(tool_context)
    if not cid:
        # No charter yet, so nothing to rank against. Recency alone decides, which is
        # the right answer when the only thing we know about the user is that they are
        # about to tell us something.
        group_facts, withheld = _facts_for_prompt(all_facts, "")
        return {
            "status": "no_challenge",
            "message": "No challenge started yet. Begin the interview from scratch.",
            "charter": {},
            "nodes": [],
            "tools": [],
            "group_facts": group_facts,
            **_withheld_note(withheld),
        }
    challenge = store.get("challenges", cid) or {}
    nodes = store.list_nodes(cid)
    live = [n for n in nodes if n.get("status") != "superseded"]
    # What this challenge is ABOUT, in one string: the outcome, its constraints, and
    # the steps still open. Node labels are in there deliberately -- what a teammate
    # needs to be reminded of depends on what is still to do, not only on the goal.
    about = " ".join([
        str(challenge.get("charter", {}).get("outcome", "")),
        " ".join(str(c) for c in (challenge.get("charter", {}).get("constraints") or [])),
        " ".join(str(n.get("label", "")) for n in live),
    ])
    # Both lookups are free when the party is under budget, and `_facts_for_prompt`
    # returns before touching either -- but they are cheap regardless: the vectors are
    # already in the group document we just read, and the goal vector is cached on the
    # challenge until its text changes.
    group_facts, withheld = _facts_for_prompt(
        all_facts, about,
        vectors=store.fact_vectors(gid) if len(all_facts) > GROUP_FACT_BUDGET else None,
        goal_vector=store.goal_vector(cid, about) if len(all_facts) > GROUP_FACT_BUDGET else None,
    )
    return {
        "status": "ok",
        "challenge_id": cid,
        "charter": challenge.get("charter", {}),
        # Superseded nodes are excluded: they belong to a plan that no longer exists,
        # and handing one to a teammate is the fastest way to look inattentive.
        "nodes": live,
        "tools": [{"node_id": t.get("node_id"), "name": t.get("name"), "type": t.get("type")}
                  for t in store.list_tools(cid)],
        "group_facts": group_facts,
        **_withheld_note(withheld),
        "recent_journal": [
            {"actor": j.get("actor"), "kind": j.get("kind"), "text": j.get("text")}
            for j in store.list_journal(cid)[-12:]
        ],
        "tool_feedback": _tool_feedback(cid),
    }


def _facts_for_prompt(facts: list[str], about: str,
                      vectors: Optional[list] = None,
                      goal_vector: Optional[list[float]] = None) -> tuple[list[str], int]:
    """The group's facts, trimmed to a budget. Returns (kept, withheld_count).

    Under the budget nothing changes at all -- no ranking, no reordering, same list in
    the same order. That matters: every live check and every recorded demo was measured
    against the unranked behaviour, and quietly re-sorting a party's memory to prove a
    scaling story would invalidate all of them for no benefit to anyone.

    Over the budget, keep the newest `GROUP_FACT_RECENT` unconditionally, then fill the
    rest by relevance to the goal. Ties go to the more recent fact. Original order is
    restored at the end, because a teammate reading the journal and a model reading this
    should see the same story in the same order.

    "Relevance" is cosine similarity between the fact's embedding and the goal's, when
    both exist. It used to be content-word overlap, and `check_fact_budget_live.py`
    caught that failing precisely where you would expect: a real discovery sharing no
    vocabulary with the charter scored zero and lost its place to newer filler. "The
    vendor never answers on Fridays" and "ship the app by the 30th" have no words in
    common and everything else in common.

    THE TWO SCALES ARE NEVER MIXED IN ONE SORT, and the first version of this got that
    wrong in a way that made production measurably worse -- 3 of 4 real facts survived
    under the pure lexical ranker, 2 of 4 under the mixed one.

    The reason is that `gemini-embedding-001` does not put unrelated text near zero.
    Measured against this product's own goal: total nonsense sits at **0.66** and a
    genuinely relevant fact at 0.72-0.83. A 0.07 band above a 0.65 floor is plenty for
    a relative ordering and useless as an absolute score -- so a fact with no vector,
    scored 0.25 on a rescaled word-overlap, lost to filler sitting at 0.66.

    So when there is a goal vector, unembedded facts are scored at the MEDIAN cosine of
    the embedded ones: explicitly neither punished nor favoured, because "we did not
    measure this" is not the same as "this is irrelevant". Word overlap then breaks
    ties among them, which is the only place it can do no harm. Run
    `scripts\\backfill_fact_vectors.py` and the mixed case stops existing.
    """
    if len(facts) <= GROUP_FACT_BUDGET:
        return list(facts), 0

    wanted = _content_words(about or "")
    vectors = list(vectors or [])
    recent_from = len(facts) - GROUP_FACT_RECENT
    candidates = list(range(recent_from))

    sims = {}
    for i in candidates:
        sim = embeddings.similarity(vectors[i] if i < len(vectors) else None, goal_vector)
        if sim > -1.0:
            sims[i] = sim

    if sims:
        ordered = sorted(sims.values())
        neutral = ordered[len(ordered) // 2]
    else:
        neutral = 0.0

    def lexical(fact: str) -> float:
        # Only ever a TIE-BREAK when vectors are in play, so its absolute scale does
        # not matter -- which is the whole point. It is the primary score only when
        # nothing has a vector at all, and then everything is on this scale together.
        if not wanted:
            return 0.0
        return min(1.0, len(wanted & _content_words(fact)) / 8.0)

    def key(i: int) -> tuple[float, float, int]:
        primary = sims.get(i, neutral if sims else lexical(facts[i]))
        return (-primary, -lexical(facts[i]), -i)

    room = max(0, GROUP_FACT_BUDGET - GROUP_FACT_RECENT)
    keep = {i for i in range(recent_from, len(facts))}
    keep |= set(sorted(candidates, key=key)[:room])
    return [facts[i] for i in sorted(keep)], len(facts) - len(keep)


def _withheld_note(withheld: int) -> dict[str, Any]:
    """Say out loud that the list is partial. Silence here would be a lie by omission.

    A model handed 40 of 96 facts with no marker will answer "is that everything the
    team knows?" with yes, in good faith, because nothing told it otherwise.
    """
    if not withheld:
        return {}
    return {
        "group_facts_withheld": withheld,
        "group_facts_note": (
            f"{withheld} older group facts were not included -- this list is the most "
            f"recent and the most relevant to this goal, not everything the party "
            f"knows. If the user asks about something you cannot see here, say the "
            f"team may know more rather than saying it is unknown."
        ),
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
