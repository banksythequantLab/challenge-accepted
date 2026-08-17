"""Shared memory only grows, and every fact is re-sent on every tool call.

`read_challenge_state` used to hand the model every group fact the party had ever
recorded -- on every call, for every agent that holds the tool, on every turn. That is
fine at nine facts and it is the product's centre of gravity, so it is guaranteed not
to stay at nine. The failure mode is the nasty kind: nothing errors, the prompt just
gets longer until the model starts missing things buried in the middle of it. A party
that has been working for a month would quietly get worse at remembering than one that
started yesterday, and nothing anywhere would say so.

The two properties that matter are in tension, so both are pinned here:

  * under the budget, NOTHING changes -- same facts, same order. Every live check and
    the recorded demo were measured against that behaviour;
  * over it, the newest survive unconditionally and the rest compete on relevance --
    and the caller is TOLD how many were dropped, because a trimmed list presented as
    the whole truth is worse than a long one.
"""

from __future__ import annotations

from challenge_accepted.services import tools

BUDGET = tools.GROUP_FACT_BUDGET
RECENT = tools.GROUP_FACT_RECENT


def test_a_small_party_is_untouched():
    facts = [f"fact {i}" for i in range(BUDGET)]
    kept, withheld = tools._facts_for_prompt(facts, "anything at all")
    assert kept == facts, "under budget this must be a passthrough, order included"
    assert withheld == 0


def test_nothing_is_withheld_silently():
    facts = [f"filler {i}" for i in range(BUDGET * 3)]
    kept, withheld = tools._facts_for_prompt(facts, "goal words")
    assert len(kept) == BUDGET
    assert withheld == len(facts) - BUDGET

    note = tools._withheld_note(withheld)
    assert note["group_facts_withheld"] == withheld
    # The model has to be able to say "the team may know more" instead of "unknown".
    assert str(withheld) in note["group_facts_note"]
    assert tools._withheld_note(0) == {}, "no marker when nothing was dropped"


def test_the_newest_facts_always_survive():
    """Recency beats the score, deliberately.

    Relevance here is content-word overlap -- a guess. Recency is a fact. The thing a
    teammate most needs is usually what somebody found out an hour ago, which is
    exactly what a bag-of-words score against an old charter ranks last.
    """
    facts = [f"old fact about widgets {i}" for i in range(BUDGET * 2)]
    newest = [f"just discovered thing {i}" for i in range(RECENT)]
    kept, _ = tools._facts_for_prompt(facts + newest, "widgets widgets widgets")
    for fact in newest:
        assert fact in kept, "a brand-new discovery was dropped for an old on-topic one"


def test_relevance_decides_the_rest():
    noise = [f"unrelated trivia number {i}" for i in range(BUDGET * 2)]
    signal = "The Vercel deploy needs the team's billing contact to approve it."
    kept, _ = tools._facts_for_prompt([signal] + noise, "vercel billing deploy approval")
    assert signal in kept, (
        "the one fact that overlaps the goal was dropped in favour of trivia -- "
        "the ranking is not reading the goal at all")


def test_order_is_preserved():
    """A teammate reading the journal and a model reading this see the same story."""
    facts = [f"step {i:03d}" for i in range(BUDGET * 2)]
    kept, _ = tools._facts_for_prompt(facts, "step")
    assert kept == sorted(kept), "facts came back out of the order they were learned in"
