"""Relevance used to mean "shares words with the goal", and that is a guess.

`check_fact_budget_live.py` measured it failing on production exactly where you would
expect: over the budget, a real discovery that happened to share no vocabulary with the
charter scored zero and lost its place to newer filler. "The vendor never answers on
Fridays" and "ship the app by the 30th" have no words in common and everything else in
common.

Facts are embedded when written, the goal when it changes, and the ranking is cosine
similarity. What these pin is the behaviour AROUND that, which is where the risk lives:

  * a store with no vectors at all must still work -- that is local development, every
    offline test, and any deployment where the embedding call is failing;
  * a MIXED store must not sort every pre-embeddings fact to the bottom, or turning
    this on would quietly amnesia a party's whole history;
  * recency still wins outright, because a ranking is a guess and "somebody found this
    out an hour ago" is not.

The vectors here are hand-written, not model output. A test that calls an embedding API
is measuring the network.

**They are hand-written to REAL numbers, though, and the first version was not.** It
used an orthogonal vector for "unrelated", which made every assertion below trivially
true and hid the actual bug: `gemini-embedding-001` does not put unrelated text near
zero. Measured against this product's own goal text:

    REAL   +0.7223  "Deadline: Christmas Eve (December 24)."
    REAL   +0.8312  "Already tried: No prior structured race training..."
    filler +0.6573  "ca-filler-001: locksmith01 closes01 customshouse01."
    filler +0.6800  "ca-filler-017: saltmarsh17 dawdles17 chandlersrow17."

The floor is ~0.65 and the signal is a 0.07 band above it. That is fine for ranking,
which is relative -- and fatal for mixing cosines with any other score, which the first
version of the ranker did. On production it made things WORSE: 3 of 4 real facts
survived under the old lexical ranker, 2 of 4 under the new one, because unembedded
real facts scored ~0.25 on the lexical scale and lost to filler sitting at 0.66.
"""

from __future__ import annotations

import math

from challenge_accepted.services import embeddings, tools

BUDGET = tools.GROUP_FACT_BUDGET
RECENT = tools.GROUP_FACT_RECENT


def unit(*parts: float) -> list[float]:
    norm = math.sqrt(sum(p * p for p in parts))
    return [p / norm for p in parts]


#: Built to sit at the measured cosines above rather than at a convenient 0 and 1.
GOAL = unit(1.0, 0.0)
ON_TOPIC = unit(0.82, 0.5724)        # cos ~= 0.82 to GOAL, like a real on-topic fact
OFF_TOPIC = unit(0.66, 0.7512)       # cos ~= 0.66 -- the FLOOR, not orthogonality


def test_no_vectors_anywhere_still_ranks_and_still_trims():
    """The offline path. If this breaks, so does every test in this repo."""
    facts = [f"note {i} about widgets" for i in range(BUDGET * 2)]
    kept, withheld = tools._facts_for_prompt(facts, "widgets")
    assert len(kept) == BUDGET
    assert withheld == len(facts) - BUDGET


def test_meaning_beats_vocabulary():
    """The bug this whole change exists for.

    The signal shares NO words with the goal. Under the old lexical ranker it scored
    zero and was dropped; with a vector it is the closest thing in the store.
    """
    signal = "The vendor never answers on Fridays."
    noise = [f"unrelated trivia number {i}" for i in range(BUDGET * 2)]
    facts = [signal] + noise
    vectors = [ON_TOPIC] + [OFF_TOPIC] * len(noise)

    kept, _ = tools._facts_for_prompt(
        facts, "ship the app by the 30th", vectors=vectors, goal_vector=GOAL)
    assert signal in kept

    # And the same call with the vectors taken away drops it -- which is both the old
    # behaviour and the proof that the assertion above is measuring the vectors rather
    # than passing for some unrelated reason.
    lexical, _ = tools._facts_for_prompt(facts, "ship the app by the 30th")
    assert signal not in lexical


def test_a_mixed_store_does_not_bury_everything_written_before_embeddings():
    """Half the party's history has vectors, half does not.

    If an unembedded fact scored below every embedded one, switching this on would
    silently drop a party's entire back catalogue on the first write after deploy.
    """
    old = [f"pre-embeddings note about deploys {i}" for i in range(20)]
    new = [f"later note about kittens {i}" for i in range(BUDGET * 2)]
    facts = old + new
    vectors = [None] * len(old) + [OFF_TOPIC] * len(new)

    kept, _ = tools._facts_for_prompt(
        facts, "deploys deploys deploys deploy pipeline release ship build",
        vectors=vectors, goal_vector=GOAL)
    survivors = [f for f in old if f in kept]
    assert survivors, ("every fact written before embeddings existed was ranked below "
                       "every fact written after, regardless of what it said")


def test_recency_is_still_unconditional():
    newest = [f"just found out thing {i}" for i in range(RECENT)]
    facts = [f"old but on topic {i}" for i in range(BUDGET * 2)] + newest
    vectors = [ON_TOPIC] * (len(facts) - RECENT) + [OFF_TOPIC] * RECENT
    kept, _ = tools._facts_for_prompt(facts, "on topic", vectors=vectors, goal_vector=GOAL)
    for fact in newest:
        assert fact in kept, "an hour-old discovery lost to an on-topic old one"


def test_a_short_vector_list_does_not_misalign_the_facts():
    """`fact_vectors` is index-aligned with `shared_facts` and can be shorter.

    Zipping them would silently pair fact 30 with vector 12 and rank on nonsense,
    which is the kind of bug that looks like the model being stupid.
    """
    facts = [f"note {i}" for i in range(BUDGET * 2)]
    kept, withheld = tools._facts_for_prompt(
        facts, "note", vectors=[ON_TOPIC, OFF_TOPIC], goal_vector=GOAL)
    assert len(kept) == BUDGET
    assert withheld == len(facts) - BUDGET


def test_similarity_says_cannot_compare_rather_than_zero():
    """0.0 is a real score -- two unrelated facts sit near it. Conflating it with
    "no vector" would let an unmeasurable fact outrank a genuinely irrelevant one."""
    assert embeddings.similarity(None, GOAL) == -1.0
    assert embeddings.similarity(GOAL, None) == -1.0
    assert embeddings.similarity([1.0, 0.0, 0.0], GOAL) == -1.0, "mismatched widths"
    assert embeddings.similarity(GOAL, GOAL) > 0.99
    # NOT near zero. Real models put unrelated short text around 0.65, which is why
    # -1.0 has to be a sentinel rather than something in the plausible score range.
    assert 0.6 < embeddings.similarity(GOAL, OFF_TOPIC) < 0.7


def test_embedding_is_off_without_a_project_and_never_raises():
    """Every entry point degrades. A tool that raises kills the whole agent turn."""
    assert embeddings.embed([]) is None
    assert embeddings.embed_one("") is None
