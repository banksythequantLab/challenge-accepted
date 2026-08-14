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
from challenge_accepted.services import session_store

AGENTS_DIR = str(Path(__file__).parent)


def _session_uri() -> str | None:
    """Where conversations live.

    Agent Engine when one exists; otherwise our own Firestore-backed service, which is
    registered under the `firestore://` scheme via ADK's service registry.

    NOT None. Passing None looks like "use the default" and reads as harmless, but ADK
    then falls back to per-agent SQLite under `<agents_dir>/<agent>/.adk/`. On Cloud
    Run that file is per-instance and ephemeral: with max-instances=10 and no session
    affinity, a judge's second message can land on an instance that has never heard of
    their session. The dashboard rebuilds it, so nothing errors -- the conversation
    history just vanishes and the interview starts over. Silent amnesia is worse than
    a visible failure, and it is the failure mode most likely to happen to someone
    else, on a laptop we are not watching.

    With no GOOGLE_CLOUD_PROJECT the store falls back to its in-memory dict, so local
    development and the test suite exercise this same path with zero GCP setup.
    """
    if config.use_vertex_sessions():
        return f"agentengine://{config.AGENT_ENGINE_ID}"
    session_store.register()
    return "firestore://sessions"


def _memory_uri() -> str | None:
    """Vertex AI Memory Bank -- personal recall across challenges.

    Personal, not shared: Memory Bank scopes memories to `(app_name, user_id)`. The
    party's shared notebook is `remember_group_fact` -> Firestore. See
    `services/memory.py` for why those are kept apart.

    Read by ADK's `preload_memory` tool on Warden and the Interviewer; written by
    `save_charter` and `complete_node`. Returning a URI here and wiring neither end
    would give us a configured service that nothing consults -- the same shape as the
    feedback button that recorded verdicts no reader ever queried.
    """
    if config.use_memory_bank():
        return f"agentengine://{config.AGENT_ENGINE_ID}"
    return None


app = get_fast_api_app(
    agents_dir=AGENTS_DIR,
    session_service_uri=_session_uri(),
    memory_service_uri=_memory_uri(),
    allow_origins=os.getenv("CA_ALLOW_ORIGINS", "*").split(","),
    web=True,                      # ADK dev UI at / -- useful for the demo video
    trace_to_cloud=config.use_memory_bank(),
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
        "vertex": config.use_memory_bank(),
        # Named separately because they are separately switchable, and because a claim
        # about Memory Bank is only checkable if the deploy will state it out loud.
        "memory": "agentengine" if config.use_memory_bank() else "none",
        "sessions": "agentengine" if config.use_vertex_sessions() else "firestore",
        "models": {"reasoning": config.MODEL_REASONING, "cheap": config.MODEL_CHEAP},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
