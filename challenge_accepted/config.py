"""Central configuration for Challenge Accepted.

Model tiering matters here. The hackathon requires "Gemini 3.5 or newer", and as of
Aug 2026 that is satisfied ONLY by the 3.5/3.6 Flash family -- gemini-3.1-pro-preview
is Google's flagship Pro model but does NOT qualify. So every agent runs on Flash, and
we split by cost: reasoning agents on 3.6 Flash, bookkeeping agents on 3.5 Flash-Lite
(5x cheaper input, 3x cheaper output).
"""

from __future__ import annotations

import os

# --- Models -----------------------------------------------------------------

#: Reasoning tier. Warden, Interviewer, Cartographer, Quartermaster, Toolwright,
#: Coach, Scout. $1.50 / $7.50 per 1M tokens.
MODEL_REASONING: str = os.getenv("CA_MODEL_REASONING", "gemini-3.6-flash")

#: Bookkeeping tier. Archivist, Referee, classifiers, summarizers.
#: $0.30 / $2.50 per 1M tokens.
MODEL_CHEAP: str = os.getenv("CA_MODEL_CHEAP", "gemini-3.5-flash-lite")

# --- Google Cloud -----------------------------------------------------------

GOOGLE_CLOUD_PROJECT: str | None = os.getenv("GOOGLE_CLOUD_PROJECT")
GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

#: Vertex AI Agent Engine ID, used for both VertexAiSessionService and
#: VertexAiMemoryBankService. Unset locally -> in-memory fallbacks.
#: Accepts a bare id or a full `projects/.../reasoningEngines/...` resource name.
AGENT_ENGINE_ID: str | None = os.getenv("AGENT_ENGINE_ID")

#: The region the Agent Engine lives in. Deliberately NOT GOOGLE_CLOUD_LOCATION.
#: In production that is "global", because Gemini 3.x is served from the global
#: endpoint -- and an Agent Engine is a regional resource that has no global form.
AGENT_ENGINE_LOCATION: str = os.getenv("AGENT_ENGINE_LOCATION", "us-central1")

#: Resource name for the Agent Runtime sandbox that Toolwright builds inside.
#: Unset locally -> BuiltInCodeExecutor (Gemini-side execution) instead.
SANDBOX_RESOURCE_NAME: str | None = os.getenv("CA_SANDBOX_RESOURCE_NAME")

# --- Behaviour knobs --------------------------------------------------------

#: Interviewer stops here. More questions than this and users bail.
MAX_CLARIFYING_QUESTIONS: int = int(os.getenv("CA_MAX_QUESTIONS", "9"))
MIN_CLARIFYING_QUESTIONS: int = int(os.getenv("CA_MIN_QUESTIONS", "5"))

#: Goal graph size bounds. Each node should be <= 2h of human effort.
MIN_NODES: int = int(os.getenv("CA_MIN_NODES", "8"))
MAX_NODES: int = int(os.getenv("CA_MAX_NODES", "20"))

#: How many Toolwright workers run concurrently in the FORGE phase.
FORGE_WORKERS: int = int(os.getenv("CA_FORGE_WORKERS", "4"))


def use_memory_bank() -> bool:
    """True when an Agent Engine exists to host Vertex AI Memory Bank."""
    return bool(GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_ID)


def agent_engine_resource() -> str | None:
    """The Agent Engine as a FULL resource name, never a bare id.

    ADK's `agentengine://` factory branches on whether the URI contains a slash. Given
    a bare id it falls back to `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION` from
    the environment -- and in this deployment `GOOGLE_CLOUD_LOCATION` is `global`,
    because Gemini 3.x is served from the global endpoint and deploying with
    `us-central1` returns `404 Publisher model ... not found`.

    An Agent Engine has no global form. A bare id would therefore build a Memory Bank
    client pointed at a region the engine does not live in. Nothing would crash at
    startup: `preload_memory` swallows search failures and `remember_session` swallows
    write failures, both by design, so the app would run perfectly and remember
    nothing. Emitting the full path takes the location out of the environment's hands.
    """
    if not (GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_ID):
        return None
    if "/" in AGENT_ENGINE_ID:
        return AGENT_ENGINE_ID
    return (f"projects/{GOOGLE_CLOUD_PROJECT}/locations/{AGENT_ENGINE_LOCATION}"
            f"/reasoningEngines/{AGENT_ENGINE_ID}")


def use_cloud_trace() -> bool:
    """Cloud Trace export. Its own switch, off by default, and that is a bug fix.

    `trace_to_cloud` was wired to the same predicate as sessions and memory. It had
    therefore never once been true in this deployment -- and the first deploy that set
    `AGENT_ENGINE_ID` proved why that mattered:

        File "/app/main.py", line 70, in <module>
          app = get_fast_api_app(
        ModuleNotFoundError: No module named 'opentelemetry.exporter'

    ADK imports `opentelemetry.exporter.cloud_trace` lazily, only when
    `trace_to_cloud=True`. The exporter was never in requirements.txt, so switching on
    Memory Bank crashed the container at import and Cloud Run refused the revision.
    Nothing was lost -- the old revision kept serving and `deploy.ps1`'s exit-code check
    reported the failure -- but a third unrelated subsystem riding on one flag is
    exactly the thing that predicate was split up to prevent.

    `opentelemetry-exporter-gcp-trace` is in requirements.txt now, so `CA_TRACE_TO_CLOUD=1`
    works. It stays off by default because a deploy should not switch on a subsystem
    nobody asked for.
    """
    return os.getenv("CA_TRACE_TO_CLOUD", "0") == "1" and bool(GOOGLE_CLOUD_PROJECT)


def use_vertex_sessions() -> bool:
    """Whether conversations live in Agent Engine instead of our own service.

    Off by default even when an Agent Engine exists, and that default is the point.
    This used to be one predicate -- `use_vertex()` -- shared by sessions and memory,
    so setting `AGENT_ENGINE_ID` to switch on Memory Bank would also have moved every
    conversation off the Firestore session service: the code with the test asserting
    `append_event` never yields to the event loop, and the fix for the per-instance
    SQLite amnesia documented in `main._session_uri`. Two unrelated subsystems behind
    one environment variable is how a proven component gets swapped for an untested one
    without a line of code changing, on the deploy where you were thinking about
    something else.

    Set `CA_SESSIONS=agentengine` to move sessions deliberately.
    """
    return use_memory_bank() and os.getenv("CA_SESSIONS", "firestore") == "agentengine"


def use_firestore() -> bool:
    """True when Firestore is reachable; otherwise the in-memory stub is used."""
    return bool(GOOGLE_CLOUD_PROJECT) and os.getenv("CA_FORCE_MEMORY_DB") != "1"
