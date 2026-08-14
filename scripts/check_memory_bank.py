"""Does Vertex AI Memory Bank actually store and return a memory? Round trip, no fakes.

The unit tests in `tests/test_memory.py` prove the app calls the memory API correctly and
survives it failing. They cannot prove the service on the other end works, because they
never reach it -- every context in there is a double. This does.

It talks to `VertexAiMemoryBankService` directly rather than through the agents, on
purpose: when the product-level check fails you want to know whether the infrastructure
is broken or the prompt is. This answers that question by itself.

Memory generation is asynchronous. Memory Bank runs a model over the ingested events to
extract and consolidate memories, so a search issued immediately after the write will
legitimately return nothing. The script polls, and a timeout is reported as a timeout --
not as a failure to store, which is a different thing and would send you debugging the
wrong end.

    set GOOGLE_CLOUD_PROJECT=...
    set AGENT_ENGINE_ID=...
    python scripts\\check_memory_bank.py

Exit code is 0 only if a memory came back carrying the fact we put in.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from google.adk.events.event import Event  # noqa: E402
from google.adk.memory.vertex_ai_memory_bank_service import (  # noqa: E402
    VertexAiMemoryBankService,
)
from google.adk.sessions.session import Session  # noqa: E402
from google.genai import types  # noqa: E402

APP = "challenge_accepted"

#: Deliberately odd. A generic fact ("I like running") could plausibly be echoed back by
#: a model that stored nothing at all; "Hollowmere" cannot be confused with anything.
NEEDLE = "Hollowmere"
FACT = (
    f"I train for the {NEEDLE} parkrun on Tuesday evenings only, because I look after "
    "my nephew every other night of the week."
)
TIMEOUT_S = int(os.getenv("CA_MEMORY_TIMEOUT", "180"))


def _turn(author: str, text: str) -> Event:
    return Event(
        author=author,
        content=types.Content(role="user" if author == "user" else "model",
                              parts=[types.Part(text=text)]),
    )


async def main() -> int:
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    engine = os.getenv("AGENT_ENGINE_ID")
    location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
    if not project or not engine:
        print("GOOGLE_CLOUD_PROJECT and AGENT_ENGINE_ID must be set.")
        return 2

    # A fresh user every run. Reusing one would let a memory from a previous run pass
    # this check while today's write silently failed.
    user = f"probe_{uuid.uuid4().hex[:10]}"
    service = VertexAiMemoryBankService(project=project, location=location,
                                        agent_engine_id=engine)
    print(f"engine   : {engine}")
    print(f"user     : {user}")

    session = Session(
        id=f"s_{uuid.uuid4().hex[:10]}",
        app_name=APP,
        user_id=user,
        events=[
            _turn("user", "I want to run a 10k under 55 minutes by Christmas."),
            _turn("interviewer", "When can you train?"),
            _turn("user", FACT),
        ],
    )

    t0 = time.time()
    await service.add_session_to_memory(session)
    print(f"write    : accepted in {time.time() - t0:.1f}s")

    # Ask the way the app asks: `preload_memory` searches with the user's own words, so
    # a check that searched for "Hollowmere" would test a retrieval path the product
    # never uses.
    query = "When is this person available to train?"
    deadline = time.time() + TIMEOUT_S
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        found = await service.search_memory(app_name=APP, user_id=user, query=query)
        if found.memories:
            print(f"read     : {len(found.memories)} memory(ies) after "
                  f"{time.time() - t0:.0f}s, {attempt} polls")
            hit = False
            for m in found.memories:
                for part in (m.content.parts or []):
                    if part.text:
                        print(f"           - {part.text.strip()[:300]}")
                        hit = hit or NEEDLE.lower() in part.text.lower()
            print()
            if hit:
                print(f"PASS: a memory came back carrying '{NEEDLE}'.")
                return 0
            print(f"FAIL: memories returned, but none mentions '{NEEDLE}'. Something "
                  "was stored -- it was not this session.")
            return 1
        await asyncio.sleep(10)

    print(f"TIMEOUT: nothing retrievable after {TIMEOUT_S}s ({attempt} polls).")
    print("         The write was accepted, so this is generation latency or a "
          "generation failure -- not a rejected call. Re-run with a longer "
          "CA_MEMORY_TIMEOUT before concluding it is broken.")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
