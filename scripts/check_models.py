"""Which models can this key actually call right now, and at what tier?

Model *visibility* (models.list) is not the same as model *access*. A key can see a
model and still get 429 on it if the project has no credits and the model has no free
tier. Run this before blaming the prompts.

    python scripts\\check_models.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from google import genai  # noqa: E402

CANDIDATES = [
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.6-flash",
]


def main() -> None:
    key = os.getenv("GOOGLE_API_KEY")
    if not key:
        sys.exit("No GOOGLE_API_KEY found.")

    client = genai.Client(api_key=key)
    print(f"key ...{key[-6:]}\n")

    for model in CANDIDATES:
        try:
            resp = client.models.generate_content(
                model=model, contents="Reply with exactly: OK"
            )
            usage = getattr(resp, "usage_metadata", None)
            tokens = getattr(usage, "total_token_count", "?") if usage else "?"
            print(f"  OK    {model:<26} reply={(resp.text or '').strip()[:12]!r} tokens={tokens}")
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).replace("\n", " ")
            code = "429" if "429" in msg or "RESOURCE_EXHAUSTED" in msg else "ERR"
            print(f"  {code}   {model:<26} {msg[:120]}")


if __name__ == "__main__":
    main()
