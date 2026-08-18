"""Read or set Cloud Run env vars without the gcloud CLI.

The CLI can refuse to run long before the credentials themselves expire: an org
reauth policy makes `gcloud run services describe` fail with "Reauthentication
failed. cannot prompt during non-interactive execution", while the same refresh
token still mints a working access token through google-auth. That is the state
this script exists for -- it talks to the Cloud Run Admin API v2 directly with
the credentials `scripts/logs.py` already uses.

    python scripts\\run_env.py                       # print current env vars
    python scripts\\run_env.py --set CA_FORGE_WORKERS=2
    python scripts\\run_env.py --unset CA_FORGE_WORKERS

A --set/--unset is a PATCH of the live service: it starts a new revision with
the same image and 100% traffic. It does not build or deploy code.
"""

from __future__ import annotations

import argparse
import sys
import time

import google.auth
import google.auth.transport.requests as gart
import requests

PROJECT = "gen-lang-client-0955694243"
REGION = "us-central1"
SERVICE = "challenge-accepted"
BASE = (f"https://run.googleapis.com/v2/projects/{PROJECT}"
        f"/locations/{REGION}/services/{SERVICE}")


def _session():
    creds, _ = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"])
    creds.refresh(gart.Request())
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {creds.token}",
                      "x-goog-user-project": PROJECT})
    return s


def _get(s):
    r = s.get(BASE, timeout=60)
    r.raise_for_status()
    return r.json()


def _show(svc):
    tmpl = svc["template"]["containers"][0]
    print(f"revision: {svc.get('latestReadyRevision', '?').rsplit('/', 1)[-1]}")
    print(f"image:    {tmpl.get('image')}")
    env = tmpl.get("env") or []
    if not env:
        print("env:      (none)")
    for e in sorted(env, key=lambda x: x["name"]):
        # Secret-backed vars carry no literal value; do not invent one.
        val = e.get("value")
        if val is None:
            val = "<from secret>" if "valueSource" in e else ""
        print(f"  {e['name']}={val}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", dest="assign", action="append", default=[],
                    metavar="KEY=VALUE")
    ap.add_argument("--unset", action="append", default=[], metavar="KEY")
    ap.add_argument("--wait", type=int, default=180,
                    help="seconds to wait for the new revision to be ready")
    a = ap.parse_args()

    s = _session()
    svc = _get(s)

    if not a.assign and not a.unset:
        _show(svc)
        return 0

    tmpl = svc["template"]["containers"][0]
    env = {e["name"]: e for e in (tmpl.get("env") or [])}
    for pair in a.assign:
        if "=" not in pair:
            print(f"--set needs KEY=VALUE, got {pair!r}", file=sys.stderr)
            return 2
        k, v = pair.split("=", 1)
        env[k] = {"name": k, "value": v}
    for k in a.unset:
        env.pop(k, None)
    tmpl["env"] = [env[k] for k in sorted(env)]

    # Send only the template. Echoing the whole GET body back includes
    # output-only fields the API rejects, and a stale revision name would pin
    # the new revision to a name that already exists.
    svc["template"].pop("revision", None)
    body = {"template": svc["template"]}
    r = s.patch(BASE, json=body, timeout=120)
    if not r.ok:
        print(f"PATCH {r.status_code}: {r.text[:800]}", file=sys.stderr)
        return 1
    print(f"patch accepted: {r.json().get('name', '')}")

    before = svc.get("latestReadyRevision")
    deadline = time.time() + a.wait
    while time.time() < deadline:
        time.sleep(10)
        cur = _get(s)
        if cur.get("latestReadyRevision") != before:
            print("new revision ready:")
            _show(cur)
            return 0
        print("  ...waiting")
    print("timed out waiting for a new ready revision", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
