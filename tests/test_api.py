"""Read API tests.

Uses the module-level `store` singleton the API reads from, seeded directly -- no
model calls. The graph endpoint is the one that matters: it is what the demo video
shows, and a layout bug there is the most visible kind of bug this project can have.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from challenge_accepted.api import router
from challenge_accepted.services.store import store


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def challenge() -> str:
    cid = store.create_challenge(
        {"outcome": "ship the app", "definition_of_done": "deployed"},
        owner_id="derek", group_id="grp_api_test",
    )
    #  spike ──┐
    #          ├─> integrate ──> deploy
    #  ui    ──┘
    store.put_node(cid, {"id": "spike", "title": "Spike", "acceptance_criteria": "a",
                         "depends_on": [], "effort_mins": 60})
    store.put_node(cid, {"id": "ui", "title": "UI", "acceptance_criteria": "b",
                         "depends_on": [], "effort_mins": 90})
    store.put_node(cid, {"id": "integrate", "title": "Integrate",
                         "acceptance_criteria": "c", "depends_on": ["spike", "ui"]})
    store.put_node(cid, {"id": "deploy", "title": "Deploy", "acceptance_criteria": "d",
                         "depends_on": ["integrate"]})
    store.put_tool(cid, "spike", {"type": "checklist", "name": "Spike Checklist",
                                  "source": "{}", "usage": "u",
                                  "smoke_test_passed": True, "degraded": False})
    store.add_journal(cid, {"actor": "derek", "kind": "insight", "text": "billing blocked"})
    store.add_group_fact("grp_api_test", "Nobody has GCP admin.")
    return cid


def test_challenge_summary(client: TestClient, challenge: str):
    body = client.get(f"/api/challenges/{challenge}").json()
    assert body["charter"]["outcome"] == "ship the app"
    assert body["counts"] == {"nodes": 4, "done": 0, "tools": 1}
    assert body["group_facts"] == ["Nobody has GCP admin."]


def test_unknown_challenge_is_404(client: TestClient):
    assert client.get("/api/challenges/nope").status_code == 404


def test_graph_lays_nodes_out_by_dependency_depth(client: TestClient, challenge: str):
    graph = client.get(f"/api/challenges/{challenge}/graph").json()
    x = {n["id"]: n["position"]["x"] for n in graph["nodes"]}

    assert x["spike"] == x["ui"] == 0, "independent roots belong in the same column"
    assert x["integrate"] == 280
    assert x["deploy"] == 560

    y = {n["id"]: n["position"]["y"] for n in graph["nodes"]}
    assert y["spike"] != y["ui"], "nodes in one column must not overlap"


def test_graph_edges_match_dependencies(client: TestClient, challenge: str):
    graph = client.get(f"/api/challenges/{challenge}/graph").json()
    assert {e["id"] for e in graph["edges"]} == {
        "spike->integrate", "ui->integrate", "integrate->deploy",
    }


def test_ready_flag_tracks_dependency_completion(client: TestClient, challenge: str):
    def ready() -> set[str]:
        graph = client.get(f"/api/challenges/{challenge}/graph").json()
        return {n["id"] for n in graph["nodes"] if n["data"]["ready"]}

    assert ready() == {"spike", "ui"}

    store.set_node_status(challenge, "spike", "done", "logs")
    assert ready() == {"ui"}, "integrate still needs ui"

    store.set_node_status(challenge, "ui", "done", "screenshot")
    assert ready() == {"integrate"}


def test_superseded_nodes_are_hidden_unless_asked_for(client: TestClient, challenge: str):
    store.supersede_nodes(challenge, ["spike", "ui", "integrate"])

    visible = client.get(f"/api/challenges/{challenge}/graph").json()
    assert "deploy" not in {n["id"] for n in visible["nodes"]}
    assert all(e["target"] != "deploy" for e in visible["edges"]), \
        "an edge pointing at a hidden node would render as a dangling arrow"

    everything = client.get(
        f"/api/challenges/{challenge}/graph", params={"include_superseded": True}
    ).json()
    assert "deploy" in {n["id"] for n in everything["nodes"]}


def test_tools_are_attached_to_their_node(client: TestClient, challenge: str):
    graph = client.get(f"/api/challenges/{challenge}/graph").json()
    spike = next(n for n in graph["nodes"] if n["id"] == "spike")
    assert [t["name"] for t in spike["data"]["tools"]] == ["Spike Checklist"]


def test_feedback_roundtrip(client: TestClient, challenge: str):
    created = client.post(f"/api/challenges/{challenge}/feedback", json={
        "target_type": "tool", "target_id": "spike", "verdict": "up",
        "reason": "caught the auth step",
    })
    assert created.status_code == 201

    listed = client.get(f"/api/challenges/{challenge}/feedback").json()["feedback"]
    assert [(f["verdict"], f["reason"]) for f in listed] == [("up", "caught the auth step")]


def test_bad_verdict_is_rejected(client: TestClient, challenge: str):
    resp = client.post(f"/api/challenges/{challenge}/feedback", json={
        "target_type": "tool", "target_id": "spike", "verdict": "maybe",
    })
    assert resp.status_code == 422


def test_journal_is_chronological(client: TestClient, challenge: str):
    store.add_journal(challenge, {"actor": "coach", "kind": "decision", "text": "second"})
    entries = client.get(f"/api/challenges/{challenge}/journal").json()["entries"]
    assert [e["text"] for e in entries] == ["billing blocked", "second"]


def test_cyclic_dependencies_do_not_hang_the_layout(client: TestClient):
    """A model can emit a cycle. The UI must still render rather than recurse forever."""
    cid = store.create_challenge({}, "u", "g_cycle")
    store.put_node(cid, {"id": "a", "title": "A", "acceptance_criteria": "x",
                         "depends_on": ["b"]})
    store.put_node(cid, {"id": "b", "title": "B", "acceptance_criteria": "x",
                         "depends_on": ["a"]})

    graph = client.get(f"/api/challenges/{cid}/graph").json()
    assert len(graph["nodes"]) == 2
