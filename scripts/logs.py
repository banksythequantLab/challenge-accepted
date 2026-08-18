"""Read Cloud Run logs without fighting PowerShell over quoting.

`gcloud logging read` takes a filter string containing spaces, colons and quotes, and
getting that through PowerShell intact cost more attempts than the query was worth.
This talks to the Logging API directly with the same credentials.

    python scripts\\logs.py "id parameter is only supported"     # substring search
    python scripts\\logs.py --severity ERROR --hours 2
    python scripts\\logs.py "ValueError" --hours 4 --limit 60
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys

import google.auth
import google.auth.transport.requests as gart
import requests

PROJECT = "gen-lang-client-0955694243"
SERVICE = "challenge-accepted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?", default=None, help="substring to look for")
    ap.add_argument("--severity", default=None)
    ap.add_argument("--hours", type=float, default=2.0)
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--full", action="store_true", help="do not truncate lines")
    a = ap.parse_args()

    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(gart.Request())

    since = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(hours=a.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [
        'resource.type="cloud_run_revision"',
        f'resource.labels.service_name="{SERVICE}"',
        f'timestamp>="{since}"',
    ]
    if a.text:
        parts.append(f'textPayload:"{a.text}"')
    if a.severity:
        parts.append(f"severity>={a.severity}")

    # `x-goog-user-project` is not optional here, it just fails slowly without it.
    # A user-credential token with no quota project bills reads to Google's shared
    # default project (number 764086051850), whose per-minute read quota is exhausted
    # by everyone on earth. The symptom is a 429 naming a project number that is not
    # yours, in the middle of debugging something else -- which is how this cost an
    # hour once. Charge the reads to the project whose logs they are.
    r = requests.post(
        "https://logging.googleapis.com/v2/entries:list",
        headers={"Authorization": f"Bearer {creds.token}",
                 "x-goog-user-project": PROJECT,
                 "Content-Type": "application/json"},
        json={"resourceNames": [f"projects/{PROJECT}"],
              "filter": " AND ".join(parts),
              "orderBy": "timestamp desc",
              "pageSize": a.limit},
        timeout=120)
    if not r.ok:
        print(f"{r.status_code} {r.text[:600]}")
        return 1

    entries = r.json().get("entries", [])
    print(f"{len(entries)} entries in the last {a.hours}h\n")
    for e in reversed(entries):
        text = (e.get("textPayload")
                or (e.get("jsonPayload") or {}).get("message") or "")
        text = text if a.full else text[:400]
        ts = e.get("timestamp", "")[11:19]
        print(f"{ts} {e.get('severity','')[:4]:<4} "
              f"{text.encode('ascii','replace').decode('ascii')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
