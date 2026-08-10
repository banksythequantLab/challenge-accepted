"""Group intelligence: what one teammate learns must reach the others.

This is the claim the whole product rests on -- goal-scoped shared memory, as opposed
to the corpus-scoped enterprise search everyone else ships. These tests pin the store
behaviour that makes it true, without needing a model.
"""

from __future__ import annotations

from challenge_accepted.services.store import Store

GROUP = "grp_team"


def _shared_challenge() -> tuple[Store, str]:
    s = Store()
    cid = s.create_challenge({"outcome": "ship the app"}, owner_id="derek", group_id=GROUP)
    for nid in ("spike", "build-ui", "deploy", "record-video"):
        s.put_node(cid, {"id": nid, "title": nid, "acceptance_criteria": "c"})
    return s, cid


def test_a_fact_one_member_saves_is_visible_to_the_group():
    s, _ = _shared_challenge()
    s.add_group_fact(GROUP, "Nobody on the team has admin on the GCP billing account.")

    facts = (s.get("groups", GROUP) or {}).get("shared_facts", [])
    assert facts == ["Nobody on the team has admin on the GCP billing account."]


def test_progress_by_one_member_is_visible_to_another():
    """Dana must not be handed a node Derek already closed."""
    s, cid = _shared_challenge()
    s.set_node_status(cid, "spike", "done", "logs committed by derek")

    open_nodes = [n["id"] for n in s.list_nodes(cid) if n["status"] == "todo"]
    assert "spike" not in open_nodes
    assert set(open_nodes) == {"build-ui", "deploy", "record-video"}

    closed = next(n for n in s.list_nodes(cid) if n["id"] == "spike")
    assert closed["evidence"] == ["logs committed by derek"]


def test_group_memory_does_not_leak_between_groups():
    """Two groups pursuing similar goals must not read each other's facts."""
    s = Store()
    s.add_group_fact("grp_a", "Our permit office only takes Tuesday appointments.")
    s.add_group_fact("grp_b", "Our vendor never replies before noon.")

    a = (s.get("groups", "grp_a") or {}).get("shared_facts", [])
    b = (s.get("groups", "grp_b") or {}).get("shared_facts", [])
    assert a == ["Our permit office only takes Tuesday appointments."]
    assert b == ["Our vendor never replies before noon."]


def test_two_members_reporting_the_same_discovery_store_it_once():
    """Derek and Dana hit the same wall an hour apart and describe it differently."""
    s, _ = _shared_challenge()
    stored_derek = s.add_group_fact(
        GROUP, "Cloud Run deployment is blocked because billing is not enabled."
    )
    stored_dana = s.add_group_fact(
        GROUP, "We cannot deploy to Cloud Run -- billing is not enabled on the project."
    )

    assert stored_derek is True
    assert stored_dana is False
    assert len((s.get("groups", GROUP) or {}).get("shared_facts", [])) == 1


def test_challenge_carries_its_group_so_a_teammate_can_resolve_it():
    """A teammate opening the challenge must be able to find the group from it."""
    s, cid = _shared_challenge()
    assert (s.get("challenges", cid) or {}).get("group_id") == GROUP
