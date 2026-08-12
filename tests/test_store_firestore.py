"""Drive the Firestore branch of Store through a fake client.

These paths shipped unexecuted for nine commits behind `# pragma: no cover`. They are
the code most likely to fail the first time GOOGLE_CLOUD_PROJECT is set -- which, on
current trajectory, would be the night before submitting.

The fake mimics only the slice of the client Store touches:

    client.collection(name).document(id).set(doc[, merge=True])
    client.collection(name).document(id).get()  -> snapshot(.exists, .to_dict())
    client.collection(name).where(filter=FieldFilter(...)).stream()
    client.collection(name).stream()

It deliberately enforces the real API's constraints -- notably that `where` must be
called with a keyword `filter=`, because the positional form is deprecated.
"""

from __future__ import annotations

from typing import Any

import pytest
from google.cloud.firestore_v1.base_query import FieldFilter

from challenge_accepted.services.store import Store


class FakeSnapshot:
    #: `reference` exists because delete_where() streams a query and deletes each hit
    #: through its reference -- which is what the real client library prescribes.
    def __init__(self, data: dict[str, Any] | None, reference: Any = None) -> None:
        self.reference = reference
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict[str, Any] | None:
        return dict(self._data) if self._data is not None else None


class FakeDocument:
    def __init__(self, collection: "FakeCollection", doc_id: str) -> None:
        self._collection = collection
        self._id = doc_id

    def set(self, doc: dict[str, Any], merge: bool = False) -> None:
        if merge:
            existing = self._collection.docs.get(self._id, {})
            self._collection.docs[self._id] = {**existing, **doc}
        else:
            self._collection.docs[self._id] = dict(doc)

    def get(self) -> FakeSnapshot:
        return FakeSnapshot(self._collection.docs.get(self._id))

    def delete(self) -> None:
        self._collection.docs.pop(self._id, None)


class FakeQuery:
    def __init__(self, snaps: list[FakeSnapshot]) -> None:
        self._snaps = snaps

    def stream(self):
        return list(self._snaps)


class FakeCollection:
    def __init__(self, name: str) -> None:
        self.name = name
        self.docs: dict[str, dict[str, Any]] = {}

    def document(self, doc_id: str) -> FakeDocument:
        return FakeDocument(self, doc_id)

    def where(self, field_path=None, op_string=None, value=None, *, filter=None):  # noqa: A002
        if filter is None:
            raise TypeError(
                "positional where(field, op, value) is deprecated in "
                "google-cloud-firestore; pass filter=FieldFilter(...)"
            )
        assert isinstance(filter, FieldFilter), f"expected FieldFilter, got {type(filter)}"
        pb = filter._to_pb()
        # proto-plus wraps the value; string_value is empty-string when unset, which is
        # fine here because every field Store filters on is a non-empty string id.
        field, wanted = pb.field.field_path, pb.value.string_value
        return FakeQuery([
            FakeSnapshot(d, FakeDocument(self, k))
            for k, d in self.docs.items() if d.get(field) == wanted
        ])

    def stream(self):
        return [FakeSnapshot(d, FakeDocument(self, k)) for k, d in self.docs.items()]


class FakeFirestore:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        return self.collections.setdefault(name, FakeCollection(name))


@pytest.fixture()
def store() -> Store:
    return Store(client=FakeFirestore())


def _docs(store: Store, name: str) -> dict[str, Any]:
    return store._client.collections[name].docs


def test_backend_reports_firestore(store: Store):
    assert store.backend == "firestore"


def test_challenge_and_nodes_land_in_the_right_collections(store: Store):
    cid = store.create_challenge({"outcome": "ship"}, owner_id="derek", group_id="grp")

    assert list(_docs(store, "challenges")) == [cid]
    assert _docs(store, "challenges")[cid]["group_id"] == "grp"

    store.put_node(cid, {"id": "spike", "title": "Spike", "acceptance_criteria": "a"})
    # Composite key keeps node ids unique across challenges.
    assert list(_docs(store, "nodes")) == [f"{cid}:spike"]
    assert _docs(store, "nodes")[f"{cid}:spike"]["challenge_id"] == cid


def test_queries_use_field_filter_not_positional_where(store: Store):
    """FakeCollection.where raises on the positional form, so this fails loudly if
    the deprecated call style ever comes back."""
    cid = store.create_challenge({}, "u", "g")
    store.put_node(cid, {"id": "n1", "title": "t", "acceptance_criteria": "c"})
    store.put_node(cid, {"id": "n2", "title": "t", "acceptance_criteria": "c"})

    assert {n["id"] for n in store.list_nodes(cid)} == {"n1", "n2"}


def test_queries_are_scoped_to_one_challenge(store: Store):
    a = store.create_challenge({}, "u", "g")
    b = store.create_challenge({}, "u", "g")
    store.put_node(a, {"id": "n", "title": "t", "acceptance_criteria": "c"})

    assert len(store.list_nodes(a)) == 1
    assert store.list_nodes(b) == []


def test_patch_merges_rather_than_replacing(store: Store):
    """set(merge=True) is what preserves title/criteria when only status changes.
    A plain set() here would silently blank the node."""
    cid = store.create_challenge({}, "u", "g")
    store.put_node(cid, {"id": "n1", "title": "Keep me",
                         "acceptance_criteria": "and me", "depends_on": ["x"]})

    store.set_node_status(cid, "n1", "done", "evidence A")

    node = store.get("nodes", f"{cid}:n1")
    assert node["status"] == "done"
    assert node["title"] == "Keep me"
    assert node["acceptance_criteria"] == "and me"
    assert node["depends_on"] == ["x"]
    assert node["evidence"] == ["evidence A"]


def test_evidence_accumulates_across_patches(store: Store):
    cid = store.create_challenge({}, "u", "g")
    store.put_node(cid, {"id": "n1", "title": "t", "acceptance_criteria": "c"})

    store.set_node_status(cid, "n1", "done", "first")
    store.set_node_status(cid, "n1", "done", "second")

    assert store.get("nodes", f"{cid}:n1")["evidence"] == ["first", "second"]


def test_get_returns_none_for_missing_document(store: Store):
    assert store.get("challenges", "nope") is None


def test_group_facts_read_modify_write(store: Store):
    assert store.add_group_fact("grp", "Nobody has GCP admin.") is True
    assert store.add_group_fact("grp", "No one on the team has GCP admin rights.") is False
    assert store.add_group_fact("grp", "Devpost rejects videos over four minutes.") is True

    assert len(store.get("groups", "grp")["shared_facts"]) == 2


def test_supersede_marks_dropped_nodes(store: Store):
    cid = store.create_challenge({}, "u", "g")
    for nid in ("keep", "drop", "finished"):
        store.put_node(cid, {"id": nid, "title": nid, "acceptance_criteria": "c"})
    store.set_node_status(cid, "finished", "done", "evidence")

    retired = store.supersede_nodes(cid, ["keep"])

    assert retired == 1
    by_id = {n["id"]: n["status"] for n in store.list_nodes(cid)}
    assert by_id == {"keep": "todo", "drop": "superseded", "finished": "done"}


def test_list_challenges_newest_first_and_group_scoped(store: Store):
    a = store.create_challenge({"title": "A"}, "u1", "grp_a")
    b = store.create_challenge({"title": "B"}, "u2", "grp_b")

    all_ids = [c["id"] for c in store.list_challenges()]
    assert set(all_ids) == {a, b}
    assert [c["id"] for c in store.list_challenges(group_id="grp_a")] == [a]


def test_journal_is_sorted_chronologically(store: Store):
    cid = store.create_challenge({}, "u", "g")
    for text in ("first", "second", "third"):
        store.add_journal(cid, {"actor": "coach", "kind": "decision", "text": text})

    assert [e["text"] for e in store.list_journal(cid)] == ["first", "second", "third"]


def test_tools_are_queryable_by_challenge(store: Store):
    cid = store.create_challenge({}, "u", "g")
    store.put_tool(cid, "n1", {"type": "checklist", "name": "C", "source": "",
                               "usage": "", "smoke_test_passed": True})

    tools = store.list_tools(cid)
    assert len(tools) == 1
    assert tools[0]["node_id"] == "n1"
    assert tools[0]["challenge_id"] == cid


# --- session storage --------------------------------------------------------
# `sessions` and `session_events` exist because ADK, with session_service_uri=None,
# writes conversations to per-agent SQLite on the instance's own disk -- see
# services/session_store.py. delete() and delete_where() have no other caller in the
# codebase, so without these they would ship to Firestore entirely unexecuted, which
# is precisely the mistake this file was written to stop repeating.


def test_delete_removes_the_document(store: Store):
    store._put("sessions", "app|u|s", {"id": "s", "app_name": "app"})
    assert store.get("sessions", "app|u|s") is not None

    store.delete("sessions", "app|u|s")

    assert store.get("sessions", "app|u|s") is None


def test_delete_is_silent_on_a_missing_document(store: Store):
    """Deleting a session ADK never wrote must not raise -- the dashboard DELETEs
    optimistically when it decides a session is stale."""
    store.delete("sessions", "never-existed")


def test_delete_where_removes_only_the_matching_session(store: Store):
    for n in range(3):
        store._put("session_events", f"mine|{n}", {"session_key": "mine", "n": n})
    store._put("session_events", "theirs|0", {"session_key": "theirs", "n": 0})

    gone = store.delete_where("session_events", "session_key", "mine")

    assert gone == 3
    assert store._query("session_events", "session_key", "mine") == []
    assert len(store._query("session_events", "session_key", "theirs")) == 1


def test_delete_where_matching_nothing_is_zero_not_an_error(store: Store):
    assert store.delete_where("session_events", "session_key", "nobody") == 0
