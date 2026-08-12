"""Feedback has to come back out, or the button is decorative.

`record_feedback` wrote a Firestore row that NOTHING in the codebase ever read. No
prompt mentioned it, `read_challenge_state` did not return it, and the Quartermaster --
which is the only agent that could act on it -- carries an `output_schema` and so has
no tools at all. So "tell it what didn't work and the next one is different" was false:
the next one was identical.

These pin the wiring end to end, short of the model call itself. What is being tested
is that the user's objection REACHES the agent that has to answer it, because that is
precisely where it was being dropped.
"""

from __future__ import annotations

from challenge_accepted import prompts
from challenge_accepted.services.store import store
from challenge_accepted.services.tools import _tool_feedback, read_challenge_state
from challenge_accepted.sub_agents.forge import quartermaster_instruction

REASON = "Too generic -- I wanted my own numbers in it, not a template."


class FakeCtx:
    def __init__(self, **state):
        self.state = dict(state)


def _challenge_with_a_rejected_tool() -> tuple[str, str]:
    cid = store.create_challenge(
        {"title": "Run a 10k", "outcome": "finish under 55 minutes"},
        owner_id="u_derek", group_id="grp_derek",
    )
    store.put_node(cid, {"id": "build-base", "title": "Build an aerobic base",
                         "acceptance_criteria": "four weeks of runs logged"})
    tid = store.put_tool(cid, "build-base", {
        "type": "calculator", "name": "Generic Pace Calculator",
        "source": "print('pace')", "usage": "Run it.",
    })
    store.add_feedback(cid, {"target_type": "tool", "target_id": tid,
                             "verdict": "down", "reason": REASON})
    return cid, tid


def test_a_rejection_comes_back_resolved_to_a_name_and_node():
    """A bare tool_ id is useless to a model. It needs the name and the node."""
    cid, _ = _challenge_with_a_rejected_tool()

    fb = _tool_feedback(cid)

    assert len(fb) == 1
    assert fb[0]["tool_name"] == "Generic Pace Calculator"
    assert fb[0]["node_id"] == "build-base"
    assert fb[0]["tool_type"] == "calculator"
    assert fb[0]["verdict"] == "down"
    assert fb[0]["reason"] == REASON


def test_rejections_are_listed_before_approvals():
    """Thumbs-down is the feedback that has to change something. Put it first."""
    cid, _ = _challenge_with_a_rejected_tool()
    good = store.put_tool(cid, "build-base", {"type": "checklist", "name": "Good One"})
    store.add_feedback(cid, {"target_type": "tool", "target_id": good,
                             "verdict": "up", "reason": "perfect"})

    verdicts = [f["verdict"] for f in _tool_feedback(cid)]
    assert verdicts[0] == "down"


def test_read_challenge_state_surfaces_the_rejection():
    cid, _ = _challenge_with_a_rejected_tool()
    ctx = FakeCtx(user_id="u_derek", group_id="grp_derek", challenge_id=cid)

    state = read_challenge_state(ctx)

    assert "tool_feedback" in state
    assert state["tool_feedback"][0]["reason"] == REASON


def test_the_users_own_words_reach_the_quartermaster():
    """The whole claim. If the objection is not in the prompt, nothing can act on it."""
    cid, _ = _challenge_with_a_rejected_tool()

    text = quartermaster_instruction(FakeCtx(challenge_id=cid))

    assert REASON in text
    assert "Generic Pace Calculator" in text
    assert "build-base" in text
    assert "REJECTED SO FAR" in text


def test_the_quartermaster_prompt_is_unchanged_when_nothing_was_rejected():
    """Do not spend tokens, or invite paranoia, on a banner with nothing in it."""
    cid = store.create_challenge({"title": "Clean prompt"}, "u_a", "grp_a")
    assert quartermaster_instruction(FakeCtx(challenge_id=cid)) == prompts.QUARTERMASTER
    assert quartermaster_instruction(FakeCtx()) == prompts.QUARTERMASTER


def test_a_thumbs_up_alone_does_not_fire_the_rejection_banner():
    cid = store.create_challenge({"title": "Happy"}, "u_a", "grp_a")
    store.put_node(cid, {"id": "n", "title": "N", "acceptance_criteria": "c"})
    tid = store.put_tool(cid, "n", {"type": "checklist", "name": "Loved It"})
    store.add_feedback(cid, {"target_type": "tool", "target_id": tid,
                             "verdict": "up", "reason": "great"})

    assert quartermaster_instruction(FakeCtx(challenge_id=cid)) == prompts.QUARTERMASTER


def test_a_rejection_with_no_reason_still_says_something_actionable():
    """An empty reason must not produce a prompt line that reads as an oversight."""
    cid = store.create_challenge({"title": "Terse"}, "u_a", "grp_a")
    store.put_node(cid, {"id": "n", "title": "N", "acceptance_criteria": "c"})
    tid = store.put_tool(cid, "n", {"type": "drill", "name": "Silent Rejection"})
    store.add_feedback(cid, {"target_type": "tool", "target_id": tid,
                             "verdict": "down", "reason": ""})

    text = quartermaster_instruction(FakeCtx(challenge_id=cid))
    assert "Silent Rejection" in text
    assert "no reason given" in text


def test_feedback_on_a_deleted_tool_does_not_crash_the_prompt():
    """Feedback outlives the tool it was about -- a replan supersedes nodes."""
    cid = store.create_challenge({"title": "Ghost"}, "u_a", "grp_a")
    store.add_feedback(cid, {"target_type": "tool", "target_id": "tool_gone",
                             "verdict": "down", "reason": "wrong shape"})

    fb = _tool_feedback(cid)
    assert fb[0]["tool_name"] is None
    text = quartermaster_instruction(FakeCtx(challenge_id=cid))
    assert "wrong shape" in text
    assert "a tool" in text  # the placeholder, not a crash or a literal None
