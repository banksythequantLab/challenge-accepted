"""The gate, exercised the way an attacker would rather than the way the UI does.

The interesting cases are not "no token is rejected" -- everyone writes that test.
They are the two places identity used to be self-declared: the user id in ADK's
session URL and the `userId` in the /run_sse body. A token that verifies perfectly is
still not permission to act as somebody else.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient

from challenge_accepted import authgate
from challenge_accepted.services import auth

ALICE = auth.Caller(uid="uid_alice", email="alice@example.com", name="Alice")


@pytest.fixture
def client(monkeypatch):
    """An app with the gate on and a stub verifier: 'good' is Alice, else rejected."""
    monkeypatch.setattr(auth, "AUTH_MODE", "required")

    def fake_verify(bearer):
        if bearer == "Bearer good":
            return ALICE
        raise auth.AuthError("bad token")

    monkeypatch.setattr(auth, "verify", fake_verify)

    app = FastAPI()
    authgate.install(app)

    @app.get("/api/challenges")
    def challenges():
        return {"ok": True}

    @app.post("/apps/{app_name}/users/{user_id}/sessions")
    def create_session(app_name: str, user_id: str):
        return {"id": "s_1", "user_id": user_id}

    @app.post("/run_sse")
    async def run_sse(request: Request):
        # Proves the body survives the gate reading it. If the replay is wrong this
        # hangs or returns an empty body, and the failure looks like a network fault.
        body = await request.json()
        return {"echo": body}

    @app.post("/run")
    async def run_streaming(request: Request):
        """Shaped like the real /run_sse: reads the body, then STREAMS.

        The streaming half is the whole point. A JSON route never triggers
        Starlette's `listen_for_disconnect`, so a gate that breaks receive() passes
        a JSON test and takes the product down.
        """
        body = await request.json()

        async def events():
            for i in range(3):
                yield f"data: {json.dumps({'i': i, 'echo': body})}\n\n".encode()

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/app")
    def shell():
        return {"shell": True}

    @app.get("/api/auth/config")
    def cfg():
        return {"enabled": True}

    return TestClient(app)


def test_no_token_is_refused(client):
    r = client.get("/api/challenges")
    assert r.status_code == 401
    # The reason has to be actionable: a bare 401 mid-demo tells nobody anything.
    assert "Sign in with Google" in r.json()["detail"]
    assert r.headers.get("WWW-Authenticate") == "Bearer"


def test_bad_token_is_refused(client):
    assert client.get("/api/challenges",
                      headers={"Authorization": "Bearer nope"}).status_code == 401


def test_non_bearer_header_is_refused(client):
    assert client.get("/api/challenges",
                      headers={"Authorization": "good"}).status_code == 401


def test_good_token_passes(client):
    r = client.get("/api/challenges", headers={"Authorization": "Bearer good"})
    assert r.status_code == 200


def test_the_shell_and_auth_config_stay_public(client):
    # Otherwise there is no way to render a sign-in button: the page that offers it
    # would itself need a token.
    assert client.get("/app").status_code == 200
    assert client.get("/api/auth/config").status_code == 200


def test_cannot_create_a_session_as_someone_else(client):
    r = client.post("/apps/challenge_accepted/users/uid_bob/sessions",
                    headers={"Authorization": "Bearer good"}, json={})
    assert r.status_code == 403
    assert "another account" in r.json()["detail"]


def test_can_create_a_session_as_yourself(client):
    r = client.post("/apps/challenge_accepted/users/uid_alice/sessions",
                    headers={"Authorization": "Bearer good"}, json={})
    assert r.status_code == 200


def test_cannot_run_as_someone_else(client):
    r = client.post("/run_sse", headers={"Authorization": "Bearer good"},
                    json={"userId": "uid_bob", "newMessage": {"parts": []}})
    assert r.status_code == 403
    assert "uid_bob" in r.json()["detail"]


def test_running_as_yourself_still_receives_the_whole_body(client):
    payload = {"userId": "uid_alice", "newMessage": {"parts": [{"text": "hello"}]}}
    r = client.post("/run_sse", headers={"Authorization": "Bearer good"}, json=payload)
    assert r.status_code == 200
    assert r.json()["echo"] == payload, "the gate consumed the body and never gave it back"


def test_a_streaming_run_delivers_all_its_events(client):
    """The regression that took the live site down.

    The gate replayed the request body on EVERY receive() call. StreamingResponse
    loops on receive() waiting for http.disconnect, got http.request a second time,
    and raised `RuntimeError: Unexpected message received: http.request` -- after the
    200 had already gone out. Every agent run on production ended in 46ms with zero
    events and no error anywhere the user could see.
    """
    payload = {"userId": "uid_alice", "newMessage": {"parts": [{"text": "hi"}]}}
    with client.stream("POST", "/run", headers={"Authorization": "Bearer good"},
                       json=payload) as r:
        assert r.status_code == 200
        chunks = [c for c in r.iter_lines() if c.strip()]
    assert len(chunks) == 3, f"stream died early: {chunks}"
    assert json.loads(chunks[-1].removeprefix("data: "))["echo"] == payload


def test_a_body_that_names_nobody_is_allowed_through(client):
    # ADK has body shapes that carry no userId. Rejecting those would break the app
    # to protect against nothing.
    r = client.post("/run_sse", headers={"Authorization": "Bearer good"},
                    json={"newMessage": {"parts": []}})
    assert r.status_code == 200


def test_gate_is_inert_when_auth_is_off(monkeypatch):
    monkeypatch.setattr(auth, "AUTH_MODE", "off")
    app = FastAPI()
    authgate.install(app)

    @app.get("/api/challenges")
    def challenges():
        return {"ok": True}

    assert TestClient(app).get("/api/challenges").status_code == 200


def test_verify_rejects_a_token_with_no_email(monkeypatch):
    """Google Sign-In only. A token without a verified email is not that flow."""
    class FakeAuthMod:
        @staticmethod
        def verify_id_token(_token):
            return {"uid": "uid_x"}

    monkeypatch.setattr(auth, "_auth_mod", FakeAuthMod)
    monkeypatch.setattr(auth, "FIREBASE_PROJECT", "proj")
    with pytest.raises(auth.AuthError, match="email"):
        auth.verify("Bearer whatever")


def test_verify_reports_why_rather_than_just_failing(monkeypatch):
    class Boom:
        @staticmethod
        def verify_id_token(_token):
            raise ValueError("Token used too early, 1786800000 < 1786800030")

    monkeypatch.setattr(auth, "_auth_mod", Boom)
    monkeypatch.setattr(auth, "FIREBASE_PROJECT", "proj")
    with pytest.raises(auth.AuthError, match="too early"):
        auth.verify("Bearer whatever")


def test_display_name_never_leaks_a_full_email():
    assert auth.Caller(uid="u", email="derek@soltis.info").display == "derek"
    assert auth.Caller(uid="uid_abcdefghijk").display == "uid_abcd"


def test_json_body_that_is_not_json_is_a_400_not_a_500(client):
    r = client.post("/run_sse", headers={"Authorization": "Bearer good",
                                         "Content-Type": "application/json"},
                    content=b"{not json")
    assert r.status_code == 400
