"""Cloud Run entrypoint.

`get_fast_api_app` gives us the ADK dev UI, the /run and /run_sse endpoints, and
session/memory wiring in one call. The Next.js front end talks to /run_sse; it
subscribes to Firestore directly for the live goal graph rather than proxying
real-time updates through here.
"""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi.responses import FileResponse
from google.adk.cli.fast_api import get_fast_api_app

from challenge_accepted import config
from challenge_accepted.api import router as api_router

AGENTS_DIR = str(Path(__file__).parent)


def _session_uri() -> str | None:
    """Vertex AI Sessions in production so Cloud Run can scale to zero safely."""
    if config.use_vertex():
        return f"agentengine://{config.AGENT_ENGINE_ID}"
    return None


def _memory_uri() -> str | None:
    """Vertex AI Memory Bank -- the semantic layer behind group intelligence."""
    if config.use_vertex():
        return f"agentengine://{config.AGENT_ENGINE_ID}"
    return None


app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    session_service_uri=_session_uri(),
    memory_service_uri=_memory_uri(),
    allow_origins=os.getenv("CA_ALLOW_ORIGINS", "*").split(","),
    web=True,                      # ADK dev UI at / -- useful for the demo video
    trace_to_cloud=config.use_vertex(),
)


#: Read API for the front end. The ADK app owns /run and /run_sse; this owns /api/*.
app.include_router(api_router)


@app.get("/app", include_in_schema=False)
def dashboard() -> FileResponse:
    """The goal graph / journal / feedback UI.

    Served by the same Cloud Run service as the agent API on purpose: one deploy, one
    origin, no CORS, no second hosting platform to fail on demo day. It is a single
    static file with no build step, so `git clone && python main.py` renders it.
    """
    return FileResponse(Path(__file__).parent / "challenge_accepted" / "static" / "app.html")


@app.get("/healthz")
def healthz() -> dict[str, object]:
    from challenge_accepted.services.store import store

    return {
        "ok": True,
        "store": store.backend,
        "vertex": config.use_vertex(),
        "models": {"reasoning": config.MODEL_REASONING, "cheap": config.MODEL_CHEAP},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
