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
AGENT_ENGINE_ID: str | None = os.getenv("AGENT_ENGINE_ID")

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


def use_vertex() -> bool:
    """True when we have enough config to talk to managed Vertex services."""
    return bool(GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_ID)


def use_firestore() -> bool:
    """True when Firestore is reachable; otherwise the in-memory stub is used."""
    return bool(GOOGLE_CLOUD_PROJECT) and os.getenv("CA_FORCE_MEMORY_DB") != "1"
