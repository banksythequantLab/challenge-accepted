"""Try to get in without an account, against the deployed service.

Every other check in this repo signs in first and then confirms the app works. That
proves nothing about auth: it is the same shape as testing a lock by using the key.
This one does the opposite -- it is the only check written from the outside, and every
assertion is something that MUST fail.

    python scripts\\check_auth_live.py https://challengeaccepted.app
    python scripts\\check_auth_live.py https://challengeaccepted.app chal_7d27c86fef8f

Passing a challenge id makes the test sharper: it proves that a specific, real plan --
one whose id you now hold, exactly as if it had leaked in a screenshot -- cannot be
read without an account.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import requests

DEFAULT_URL = "https://challengeaccepted.app"
APP_NAME = "challenge_accepted"

#: A structurally valid JWT signed by nobody. If this is accepted, the server is
#: decoding tokens instead of verifying them -- which looks identical in a demo.
FORGED = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJ1aWQiOiJ1aWRfYXR0YWNrZXIiLCJlbWFpbCI6ImF0dGFja2VyQGV4YW1wbGUuY29tIiwic3ViIjoi"
    "dWlkX2F0dGFja2VyIiwiZXhwIjo5OTk5OTk5OTk5fQ."
    "c2lnbmF0dXJlLXRoYXQtaXMtbm90LWEtc2lnbmF0dXJl"
)


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL).rstrip("/")
    cid = sys.argv[2] if len(sys.argv) > 2 else None
    bad: list[str] = []

    health = requests.get(f"{base}/api/healthz", timeout=60).json()
    _p(f"auth mode  : {health.get('auth')}   configured: {health.get('auth_configured')}")
    if health.get("auth") != "required":
        _p("\nThis service is NOT running with auth required. Nothing below would mean\n"
           "anything, so the check stops here rather than printing a row of ticks.")
        return 1

    def must_fail(label: str, resp, allowed=(401, 403)) -> None:
        ok = resp.status_code in allowed
        _p(f"  {'blocked' if ok else 'GOT IN '}  {resp.status_code:<4} {label}")
        if not ok:
            bad.append(f"{label} returned {resp.status_code}, expected one of {allowed}")

    _p("\nwithout any token:")
    must_fail("GET /api/challenges", requests.get(f"{base}/api/challenges", timeout=60))
    must_fail("GET /api/me", requests.get(f"{base}/api/me", timeout=60))
    if cid:
        must_fail(f"GET /api/challenges/{cid}/dashboard",
                  requests.get(f"{base}/api/challenges/{cid}/dashboard", timeout=60))
        must_fail(f"GET /api/challenges/{cid}/tools",
                  requests.get(f"{base}/api/challenges/{cid}/tools", timeout=60))
        must_fail(f"GET /api/challenges/{cid}/journal",
                  requests.get(f"{base}/api/challenges/{cid}/journal", timeout=60))

    # The agent surface, which is where the money is: an unauthenticated /run_sse is a
    # free Gemini endpoint on someone else's bill.
    user = "u_" + uuid.uuid4().hex[:8]
    must_fail("POST /apps/.../sessions  (creating a session)",
              requests.post(f"{base}/apps/{APP_NAME}/users/{user}/sessions",
                            json={"state": {}}, timeout=60))
    must_fail("POST /run_sse            (running the agents)",
              requests.post(f"{base}/run_sse", timeout=60, json={
                  "appName": APP_NAME, "userId": user, "sessionId": "s_x",
                  "newMessage": {"role": "user", "parts": [{"text": "hello"}]}}))

    _p("\nwith a forged token:")
    forged = {"Authorization": f"Bearer {FORGED}"}
    must_fail("GET /api/challenges", requests.get(f"{base}/api/challenges",
                                                  headers=forged, timeout=60))
    must_fail("POST /run_sse", requests.post(f"{base}/run_sse", headers=forged,
                                             timeout=60, json={"userId": "x"}))

    # --- the second lock ---------------------------------------------------------
    # A door that only stops people without accounts is not a door. Anyone can get a
    # Google account in ninety seconds, so the question that actually matters is what
    # a *signed-in stranger* can see. This is the only assertion here that exercises
    # `_mine()` rather than the token check, and it needs a REAL token -- a forged one
    # dies at the gate and would pass this section for the wrong reason.
    if cid:
        _p("\nsigned in, but not on this challenge's party:")
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            from testauth import mint

            stranger = {"Authorization": "Bearer " + mint()}
        except Exception as e:  # noqa: BLE001 -- credentials, not logic
            _p(f"  SKIPPED  could not mint a test identity: {type(e).__name__}: {e}")
            bad.append("the membership wall went unmeasured -- minting a real token "
                       "failed, so nothing here tested `_mine()`")
        else:
            for path in ("dashboard", "tools", "journal"):
                must_fail(f"GET /api/challenges/{cid}/{path}",
                          requests.get(f"{base}/api/challenges/{cid}/{path}",
                                       headers=stranger, timeout=60), allowed=(403,))
            r = requests.get(f"{base}/api/challenges", headers=stranger, timeout=60)
            listed = r.json() if r.ok else []
            listed = listed.get("challenges", listed) if isinstance(listed, dict) else listed
            ids = [c.get("id") for c in listed] if isinstance(listed, list) else []
            _p(f"  {'ok     ' if cid not in ids else 'LEAKED '}  {r.status_code:<4} "
               f"GET /api/challenges lists {len(ids)} of their own")
            if cid in ids:
                bad.append(f"{cid} appears in a stranger's challenge list")

    _p("\nwhat must STILL be reachable (or nobody can sign in):")
    for label, url in (("GET /app", f"{base}/app"),
                       ("GET /api/auth/config", f"{base}/api/auth/config"),
                       ("GET /api/healthz", f"{base}/api/healthz")):
        r = requests.get(url, timeout=60)
        _p(f"  {'ok     ' if r.ok else 'BROKEN '}  {r.status_code:<4} {label}")
        if not r.ok:
            bad.append(f"{label} returned {r.status_code} -- the sign-in page cannot load")

    cfg = requests.get(f"{base}/api/auth/config", timeout=60).json()
    if not cfg.get("enabled"):
        bad.append("auth is required but /api/auth/config says it is not configured -- "
                   "the front end has no project to sign in to")
    for leak in ("clientSecret", "privateKey", "serviceAccount"):
        if leak in cfg:
            bad.append(f"/api/auth/config exposes {leak}")

    # The ADK dev UI runs agents with any user id you type into it. It has no place on
    # an authenticated deployment, and it is the sort of thing that stays switched on.
    devui = requests.get(f"{base}/dev-ui/", timeout=60, allow_redirects=False)
    _p(f"\nADK dev UI : {devui.status_code} "
       f"({'closed' if devui.status_code >= 400 else 'OPEN'})")
    if devui.status_code < 400:
        bad.append("the ADK dev UI is still served -- an unauthenticated console that "
                   "can run agents as any user id")

    if bad:
        _p("\n--- problems ---")
        for x in bad:
            _p(" * " + x)
        return 1
    _p("\nPASS -- no way in without a Google account.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
