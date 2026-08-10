"""Store tests -- the shared data source, exercised against the in-memory backend."""

from __future__ import annotations

from challenge_accepted.services.store import Store


def _store() -> Store:
    return Store()


def test_challenge_nodes_and_journal_roundtrip():
    s = _store()
    cid = s.create_challenge({"outcome": "run a 10k"}, owner_id="u1", group_id="g1")

    s.put_node(cid, {"id": "buy-shoes", "title": "Buy shoes",
                     "acceptance_criteria": "Shoes in hand", "depends_on": []})
    s.put_node(cid, {"id": "week-one", "title": "Week one",
                     "acceptance_criteria": "3 runs logged", "depends_on": ["buy-shoes"]})

    nodes = s.list_nodes(cid)
    assert {n["id"] for n in nodes} == {"buy-shoes", "week-one"}
    assert all(n["status"] == "todo" for n in nodes)

    s.add_journal(cid, {"actor": "Coach", "kind": "decision", "text": "started"})
    assert len(s.list_journal(cid)) == 1


def test_completing_a_node_appends_evidence():
    s = _store()
    cid = s.create_challenge({}, "u1", "g1")
    s.put_node(cid, {"id": "n1", "title": "t", "acceptance_criteria": "c"})

    s.set_node_status(cid, "n1", "done", "screenshot of Strava")
    s.set_node_status(cid, "n1", "done", "second proof")

    node = s.get("nodes", f"{cid}:n1")
    assert node["status"] == "done"
    assert node["evidence"] == ["screenshot of Strava", "second proof"]


def test_group_facts_are_deduplicated():
    s = _store()
    s.add_group_fact("g1", "Permit office only takes Tuesday appointments")
    s.add_group_fact("g1", "Permit office only takes Tuesday appointments")
    s.add_group_fact("g1", "Vendor never replies before noon")

    assert len(s.get("groups", "g1")["shared_facts"]) == 2


def test_challenges_are_isolated_from_each_other():
    s = _store()
    a = s.create_challenge({}, "u1", "g1")
    b = s.create_challenge({}, "u2", "g2")
    s.put_node(a, {"id": "n", "title": "t", "acceptance_criteria": "c"})

    assert len(s.list_nodes(a)) == 1
    assert s.list_nodes(b) == []


def test_falls_back_to_memory_backend_without_gcp():
    assert _store().backend == "memory"
