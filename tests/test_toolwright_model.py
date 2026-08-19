"""The Toolwright's model is its own decision, and it must not drift silently.

FORGE is the only phase whose latency the user sits and watches: one batch of
Toolwrights costs whatever the slowest one costs, measured at 2m57s of a ~4m44s cold
run on the deployed service. That is the number the 4-minute demo cap has to fit
inside, so the Toolwright's model is a knob worth having separately from the
conversational agents -- who are fast between turns and would get worse on a cheaper
tier for no visible gain.

What these pin:

  * the split exists and defaults to the reasoning tier, so nothing changed by
    accident the day it was added;
  * every Toolwright uses it -- one worker left on the old constant would make the
    batch time depend on which slot got the slow model, which is the kind of result
    that looks like flakiness;
  * `/api/healthz` reports it, because "which model built these tools" is the first
    question to ask when a deployment starts shipping worse ones, and a setting you
    cannot read from outside is a setting nobody checks.
"""

from __future__ import annotations

import importlib

from challenge_accepted import config
from challenge_accepted.sub_agents.forge import forge


def _toolwrights():
    """Every Toolwright in the built tree, found rather than assumed."""
    out = []
    stack = list(forge.sub_agents)
    while stack:
        agent = stack.pop()
        if getattr(agent, "name", "").startswith("toolwright_"):
            out.append(agent)
        stack.extend(getattr(agent, "sub_agents", None) or [])
    return out


def test_the_split_defaults_to_the_reasoning_tier():
    """Adding a knob must not move anything until somebody turns it."""
    assert config.MODEL_TOOLWRIGHT == config.MODEL_REASONING


def test_every_toolwright_uses_it():
    workers = _toolwrights()
    assert len(workers) == config.FORGE_WORKERS, (
        f"found {len(workers)} Toolwrights, expected {config.FORGE_WORKERS}")
    for w in workers:
        assert w.model == config.MODEL_TOOLWRIGHT, w.name


def test_the_env_var_actually_takes(monkeypatch):
    """A knob nobody proved works is a knob that silently does nothing -- which is
    exactly how `CA_FORGE_WORKERS` would have wasted an afternoon if it had not."""
    monkeypatch.setenv("CA_MODEL_TOOLWRIGHT", "gemini-3.5-flash")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MODEL_TOOLWRIGHT == "gemini-3.5-flash"
        assert reloaded.MODEL_REASONING != "gemini-3.5-flash", (
            "the override must not drag the conversational agents down with it")
    finally:
        monkeypatch.delenv("CA_MODEL_TOOLWRIGHT", raising=False)
        importlib.reload(config)


def test_healthz_reports_it():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from challenge_accepted.api import router

    app = FastAPI()
    app.include_router(router)
    models = TestClient(app).get("/api/healthz").json()["models"]
    assert models["toolwright"] == config.MODEL_TOOLWRIGHT
