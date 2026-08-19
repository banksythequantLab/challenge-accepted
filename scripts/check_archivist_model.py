"""Is Gemma actually serving the Archivist, and can it still call a tool?

`tests/test_archivist_model.py` pins the wiring. It cannot answer the two questions
that decide whether this was a good idea, because both are about a Google endpoint:

  1. Does `gemma-4-26b-a4b-it-maas` answer at all, on the credentials and the endpoint
     this app already uses? It is Model-as-a-Service and PUBLIC_PREVIEW, which means
     the id, the region and the availability can all move under us.
  2. Does it emit a `function_call` part, or does it answer in prose?

The second one is the whole risk. The Archivist's job is to CALL `write_journal` and
`remember_group_fact`. A model that understands the request perfectly and replies
"Sure, I've noted that down" produces an agent that looks healthy, logs nothing, and
takes the party's shared memory with it -- and this repo has already shipped one agent
that claimed a write it had no tool to perform. Prose instead of a tool call is the
same failure with a different cause.

So this asks the model directly, with the Archivist's own tools attached.

    python scripts\\check_archivist_model.py                  # the configured model
    python scripts\\check_archivist_model.py --model gemini-3.5-flash-lite

Exits non-zero if the model does not answer, or answers without calling a tool.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from google import genai                                        # noqa: E402
from google.genai import types                                  # noqa: E402

from challenge_accepted import config                           # noqa: E402

#: A turn the Archivist would be handed in production: something was discovered, and
#: it is the kind of thing a teammate joining later needs to inherit.
TURN = (
    "The user said: 'I checked and Cloud Run needs billing enabled, and nobody on the "
    "team has GCP admin. So we're hosting on Vercel instead.' Record what was learned."
)

#: The Archivist's real tools, declared the way ADK declares them. Using the actual
#: shapes matters -- a model can manage a one-string toy function and still fall over
#: on the nested one it will meet in production.
TOOLS = types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="write_journal",
        description="Record a visible journal entry against the challenge.",
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "challenge_id": types.Schema(type=types.Type.STRING),
                "kind": types.Schema(type=types.Type.STRING,
                                     description="question | answer | note | decision"),
                "text": types.Schema(type=types.Type.STRING),
            },
            required=["challenge_id", "kind", "text"])),
    types.FunctionDeclaration(
        name="remember_group_fact",
        description=("Record a durable fact the whole party and future sessions "
                     "should inherit."),
        parameters=types.Schema(
            type=types.Type.OBJECT,
            properties={
                "group_id": types.Schema(type=types.Type.STRING),
                "fact": types.Schema(type=types.Type.STRING),
            },
            required=["group_id", "fact"])),
])


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--model", default=config.MODEL_ARCHIVIST)
    ap.add_argument("--project", default=config.GOOGLE_CLOUD_PROJECT)
    ap.add_argument("--location", default=config.GOOGLE_CLOUD_LOCATION)
    args = ap.parse_args()

    if not args.project:
        return _fail("GOOGLE_CLOUD_PROJECT is unset, so there is nothing to ask.")

    _p(f"model    : {args.model}")
    _p(f"project  : {args.project}")
    _p(f"location : {args.location}")

    client = genai.Client(vertexai=True, project=args.project, location=args.location)

    started = time.time()
    try:
        r = client.models.generate_content(
            model=args.model,
            contents=(f"challenge_id is 'chal_demo', group_id is 'grp_demo'.\n{TURN}"),
            config=types.GenerateContentConfig(tools=[TOOLS]))
    except Exception as exc:                                       # noqa: BLE001
        msg = str(exc)
        hint = ""
        if "only available via global endpoint" in msg:
            hint = ("\n    This model is served from the global endpoint only. "
                    "GOOGLE_CLOUD_LOCATION must be 'global'.")
        elif "was not found or your project does not have access" in msg:
            hint = ("\n    Either the id moved (it is PUBLIC_PREVIEW) or Model Garden "
                    "access has not been granted for this project.")
        return _fail(f"{type(exc).__name__}: {msg[:400]}{hint}")

    elapsed = time.time() - started
    parts = r.candidates[0].content.parts if r.candidates else []
    calls = [p.function_call for p in parts if getattr(p, "function_call", None)]
    said = (r.text or "").strip()

    _p(f"\nlatency  : {elapsed:.2f}s")
    u = getattr(r, "usage_metadata", None)
    if u:
        _p(f"tokens   : prompt={u.prompt_token_count} out={u.candidates_token_count}")
    _p(f"prose    : {said[:160]!r}" if said else "prose    : (none, which is correct)")

    if not calls:
        return _fail(
            "the model answered without calling a tool. As the Archivist this is the "
            "worst available outcome: the agent would look healthy, the journal would "
            "stay empty, and the party's shared memory would quietly stop growing. "
            f"It said: {said[:300]!r}")

    _p(f"\ntool calls ({len(calls)}):")
    for c in calls:
        _p(f"  {c.name}({', '.join(f'{k}={v!r}' for k, v in (c.args or {}).items())})")

    names = {c.name for c in calls}
    if "remember_group_fact" not in names:
        _p("\nNOTE: it journalled but did not record a group fact. Not a failure -- the "
           "prompt decides that, not the model -- but the collaborative demo depends "
           "on group facts, so check_party_live.py is the one that matters next.")

    _p("\nPASS -- the open model answers on the app's own credentials and calls the "
       "Archivist's tools rather than describing them.")
    return 0


def _fail(msg: str) -> int:
    _p(f"\nFAIL: {msg}")
    _p("\nBack out in one command, no rebuild:\n"
       "    gcloud run services update challenge-accepted --region us-central1 "
       "--update-env-vars CA_MODEL_ARCHIVIST=gemini-3.5-flash-lite")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
