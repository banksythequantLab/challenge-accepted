"""Re-planning and group-memory hygiene.

Both behaviours here were found by running the CLIMB phase live. Neither was visible
as an error -- the system reported success while producing a mess.
"""

from __future__ import annotations

from challenge_accepted.services.store import Store, _content_words, _similar

# The three phrasings a single live run actually stored for ONE constraint.
LIVE_DUPLICATES = [
    "User lacks admin privileges on Google account required to enable Cloud Run billing.",
    "User lacks admin access on Google account required to enable billing for Cloud Run.",
    "Cloud Run requires Google account admin access to enable billing, which the user "
    "does not have.",
]


def _seeded() -> tuple[Store, str]:
    s = Store()
    cid = s.create_challenge({"outcome": "ship it"}, "u1", "g1")
    for nid in ("spike", "build-ui", "deploy-cloud-run", "record-video"):
        s.put_node(cid, {"id": nid, "title": nid, "acceptance_criteria": "c"})
    return s, cid


def test_redraw_supersedes_nodes_the_new_graph_dropped():
    s, cid = _seeded()
    s.set_node_status(cid, "spike", "done", "logs committed")

    # Replan: Cloud Run is out, Vercel is in.
    for nid in ("spike", "build-ui", "deploy-vercel", "record-video"):
        s.put_node(cid, {"id": nid, "title": nid, "acceptance_criteria": "c"})
    retired = s.supersede_nodes(cid, ["spike", "build-ui", "deploy-vercel", "record-video"])

    assert retired == 1
    by_id = {n["id"]: n for n in s.list_nodes(cid)}
    assert by_id["deploy-cloud-run"]["status"] == "superseded"
    assert by_id["deploy-vercel"]["status"] == "todo"

    active = [n for n in s.list_nodes(cid) if n["status"] != "superseded"]
    assert len(active) == 4, "a redraw must replace the plan, not stack a second one on it"


def test_finished_work_survives_a_redraw():
    """A node already done keeps its status and evidence even if the new graph drops it."""
    s, cid = _seeded()
    s.set_node_status(cid, "deploy-cloud-run", "done", "deployed and smoke-tested")

    s.supersede_nodes(cid, ["spike"])

    node = s.get("nodes", f"{cid}:deploy-cloud-run")
    assert node["status"] == "done"
    assert node["evidence"] == ["deployed and smoke-tested"]


def test_reworded_group_facts_collapse_to_one():
    s = Store()
    stored = [s.add_group_fact("g1", f) for f in LIVE_DUPLICATES]

    assert stored == [True, False, False], (
        "three phrasings of one constraint were stored separately; a teammate reading "
        "the group facts sees noise instead of intelligence"
    )
    assert len(s.get("groups", "g1")["shared_facts"]) == 1


def test_genuinely_different_facts_are_both_kept():
    s = Store()
    assert s.add_group_fact("g1", "The permit office only takes Tuesday appointments.")
    assert s.add_group_fact("g1", "The vendor never replies before noon.")
    assert len(s.get("groups", "g1")["shared_facts"]) == 2


def test_similarity_helper_edges():
    assert _similar(_content_words("Cloud Run needs billing enabled"),
                    _content_words("Billing must be enabled for Cloud Run"))
    assert not _similar(_content_words("Cloud Run needs billing enabled"),
                        _content_words("The demo video must be under four minutes"))
