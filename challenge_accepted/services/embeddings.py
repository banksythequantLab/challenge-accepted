"""Vectors for the party's shared memory, so relevance stops meaning "shares words".

`read_challenge_state` can only hand the model a bounded slice of a party's facts, and
until now it chose that slice by counting content-word overlap with the goal. That is a
guess dressed as a ranking, and `check_fact_budget_live.py` measured it failing exactly
where you would expect: a real discovery that happened to share no vocabulary with the
charter lost its place to newer noise. "The vendor never answers on Fridays" and "goal:
ship the app by the 30th" have no words in common and everything else in common.

So facts get embedded when they are written, the goal gets embedded when it changes,
and the ranking is cosine similarity between them. Two properties matter more than the
accuracy:

  * NOTHING here may raise. An embedding call is a network round trip inside a
    Firestore write inside a tool call inside an agent turn, and a tool that raises
    kills the whole invocation -- that exact chain took down a run once already. Every
    entry point returns None on failure and the caller falls back to the lexical
    ranker, which is worse but is not an outage.
  * It must be OFF-able and absent-able. Local development has no GCP credentials, and
    every offline test must keep working with no vectors in the store at all.
"""

from __future__ import annotations

import logging
import math
import os
from typing import Optional

from .. import config

logger = logging.getLogger(__name__)

#: 3072 is the model's native width. 256 is plenty to rank a few hundred short facts,
#: and the difference is not academic: these vectors live in the group document that
#: `read_challenge_state` loads on every single tool call, so width is read cost on the
#: hot path, not just storage. Truncation is the documented way to shorten them.
DIM = int(os.getenv("CA_EMBED_DIM", "256"))

MODEL = os.getenv("CA_EMBED_MODEL", "gemini-embedding-001")

#: Off by default nowhere -- it follows Vertex, because that is the only place this
#: deployment has credentials for. `CA_EMBED=off` turns it off outright, which is how
#: you find out whether the lexical fallback still works without deleting anything.
_DISABLED = os.getenv("CA_EMBED", "").lower() in ("0", "off", "false")

_client = None
_broken = False


def available() -> bool:
    return not _DISABLED and not _broken and bool(config.GOOGLE_CLOUD_PROJECT)


def _get_client():
    global _client, _broken
    if _client is not None or _broken:
        return _client
    try:  # pragma: no cover - requires GCP creds
        from google import genai

        _client = genai.Client(
            vertexai=True,
            project=config.GOOGLE_CLOUD_PROJECT,
            location=config.GOOGLE_CLOUD_LOCATION or "global",
        )
    except Exception as exc:  # pragma: no cover - requires GCP creds
        # Once, loudly, then never again. A per-call warning on a broken client would
        # be one log line per tool call per turn, which is how a real signal gets
        # buried under an alert nobody reads.
        logger.warning("embeddings unavailable, falling back to lexical ranking: %s", exc)
        _broken = True
    return _client


def embed(texts: list[str], task: str = "RETRIEVAL_DOCUMENT") -> Optional[list[list[float]]]:
    """Vectors for `texts`, or None if embeddings are off, broken or refused.

    `task` matters more than it looks. A stored fact is a DOCUMENT and the goal we
    rank against is a QUERY; embedding both the same way measurably blurs the
    asymmetry these models are trained for.
    """
    texts = [t for t in texts if isinstance(t, str) and t.strip()]
    if not texts or not available():
        return None
    client = _get_client()
    if client is None:
        return None
    try:  # pragma: no cover - requires GCP creds
        from google.genai import types

        resp = client.models.embed_content(
            model=MODEL, contents=texts,
            config=types.EmbedContentConfig(task_type=task, output_dimensionality=DIM))
        out = [list(e.values or []) for e in (resp.embeddings or [])]
        if len(out) != len(texts) or not all(out):
            logger.warning("embedding returned %d vectors for %d texts", len(out), len(texts))
            return None
        return [_unit(v) for v in out]
    except Exception as exc:  # pragma: no cover - requires GCP creds
        logger.warning("embedding call failed: %s", exc)
        return None


def embed_one(text: str, task: str = "RETRIEVAL_DOCUMENT") -> Optional[list[float]]:
    got = embed([text], task=task)
    return got[0] if got else None


def _unit(vec: list[float]) -> list[float]:
    """Normalised once, at write time.

    `output_dimensionality` truncates rather than re-projects, so a shortened vector is
    NOT unit length any more -- Google's own guidance is to renormalise. Doing it here
    means `similarity` is a plain dot product on the hot path instead of two square
    roots per fact per call.
    """
    norm = math.sqrt(sum(x * x for x in vec))
    return [x / norm for x in vec] if norm else vec


def similarity(a: Optional[list[float]], b: Optional[list[float]]) -> float:
    """Cosine, assuming both sides came through `_unit`. -1.0 means "cannot compare".

    A sentinel rather than 0.0, because 0.0 is a real score -- two unrelated facts sit
    near it -- and conflating "unrelated" with "unmeasurable" would let an unembedded
    fact quietly outrank a genuinely irrelevant one.
    """
    if not a or not b or len(a) != len(b):
        return -1.0
    return sum(x * y for x, y in zip(a, b))
