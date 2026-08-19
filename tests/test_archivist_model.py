"""The Archivist runs on Gemma, and that has to stay true where it can be seen.

Three rungs of one ladder: the reasoning tier where judgement is needed, Flash-Lite for
bookkeeping, and an open model for the one agent that only transcribes. The Archivist
reads a turn and records what was learned -- it does not decide, plan, grade evidence
or write code -- and its output is purely additive, so a weaker answer costs a thinner
journal entry rather than a broken phase. No other agent in the tree has that shape.

What these pin, and why each one is here rather than assumed:

  * the Archivist actually holds `MODEL_ARCHIVIST`. A default that is never read is the
    most common way a "configurable" model turns out to be a comment;
  * the default is Gemma and NOT the bookkeeping tier, because the whole claim is that
    an open model is serving. A silent fallback to Flash-Lite would leave the config
    comment, the healthz field and the write-up all saying something untrue;
  * nothing else in the tree got moved with it -- this is one agent's decision, and the
    Referee sharing the bookkeeping tier makes it easy to catch the wrong one;
  * the env var takes, so the knob is real and Gemma can be backed out in one
    `gcloud run services update` if it disappoints, without a deploy;
  * `/api/healthz` reports it, because "is Gemma really serving?" should be answerable
    from outside rather than by reading a deploy log.

What these deliberately do NOT do is call the model. Whether a MaaS Gemma answers, and
whether it emits `function_call` parts rather than prose -- which is the difference
between an Archivist that records and one that silently stops recording -- is a live
question about a Google endpoint, not about this repo's wiring.
`scripts/check_archivist_model.py` asks it against the real service.
"""

from __future__ import annotations

import importlib

from challenge_accepted import config
from challenge_accepted.sub_agents.archivist import archivist
from challenge_accepted.sub_agents.referee import referee


def test_the_archivist_holds_the_open_model():
    assert archivist.model == config.MODEL_ARCHIVIST


def test_the_default_is_gemma_and_not_the_bookkeeping_tier():
    assert config.MODEL_ARCHIVIST.startswith("gemma-"), config.MODEL_ARCHIVIST
    assert config.MODEL_ARCHIVIST != config.MODEL_CHEAP
    assert config.MODEL_ARCHIVIST != config.MODEL_REASONING


def test_it_is_maas_so_no_endpoint_has_to_be_deployed():
    """`-maas` is the whole reason this was affordable to do.

    The other way to reach Gemma on Vertex is a Model Garden endpoint on a GPU, which
    is a machine somebody has to remember to turn off. Losing the suffix would still
    look like a Gemma id in every log line while quietly meaning something else --
    a 404 at best, a billed accelerator at worst.
    """
    assert config.MODEL_ARCHIVIST.endswith("-maas"), config.MODEL_ARCHIVIST


def test_nothing_else_moved_with_it():
    """The Referee is the control. It shares the old tier and must stay there."""
    assert referee.model == config.MODEL_CHEAP
    assert referee.model != config.MODEL_ARCHIVIST


def test_the_env_var_actually_takes(monkeypatch):
    """The back-out path. If Gemma disappoints, this is how it is reverted without a
    rebuild -- so it has to be proved rather than assumed."""
    monkeypatch.setenv("CA_MODEL_ARCHIVIST", "gemini-3.5-flash-lite")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.MODEL_ARCHIVIST == "gemini-3.5-flash-lite"
    finally:
        monkeypatch.delenv("CA_MODEL_ARCHIVIST", raising=False)
        importlib.reload(config)


def test_healthz_reports_it():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from challenge_accepted.api import router

    app = FastAPI()
    app.include_router(router)
    models = TestClient(app).get("/api/healthz").json()["models"]
    assert models["archivist"] == config.MODEL_ARCHIVIST
