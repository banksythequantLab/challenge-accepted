"""Mint a real Firebase ID token for a throwaway test identity.

Turning on Google Sign-In cost this project something that is easy to overlook: every
live check against production started returning 401. That is not a small loss. The
FORGE outage, the Quartermaster JSON dump and the SSE outage were all found by driving
the deployed service, and none of them were visible from a unit test.

So the checks need to be able to sign in. They do it the way an administrator would,
not the way a user would:

    custom token (signed by the Firebase admin service account)
      -> accounts:signInWithCustomToken   (Identity Toolkit, public API key)
      -> a real ID token the server verifies exactly like a browser's

This is NOT a hole in the sign-in wall. Minting a custom token requires
`iam.serviceAccounts.signBlob` on the project's Firebase admin service account -- it is
an owner-level capability. Anyone who can run this could already read Firestore
directly.

    python scripts\\testauth.py                  # print a token
    python scripts\\testauth.py --uid t_alice    # a specific test identity

Used as a module by the live checks:

    from testauth import mint
    headers = {"Authorization": "Bearer " + mint()}
"""

from __future__ import annotations

import argparse
import os
import sys
import uuid

import requests

PROJECT = os.getenv("CA_FIREBASE_PROJECT", "gen-lang-client-0955694243")
ADMIN_SA = os.getenv(
    "CA_ADMIN_SA", f"firebase-adminsdk-fbsvc@{PROJECT}.iam.gserviceaccount.com")

#: The browser API key. Public by design -- it identifies the project to Identity
#: Toolkit and authorises nothing on its own.
API_KEY = os.getenv("CA_FIREBASE_API_KEY", "AIzaSyARm_kmOgBLeG_2C5ayqI_Xk4v3-EnVxtI")

#: Test identities are prefixed so they are obvious in the Firestore console and in a
#: party roster. A check that leaves data behind should leave data that says so.
PREFIX = "ca_test_"

_app = None


def _init():
    global _app
    if _app is None:
        import firebase_admin

        if not firebase_admin._apps:
            firebase_admin.initialize_app(options={
                "projectId": PROJECT, "serviceAccountId": ADMIN_SA})
        _app = firebase_admin.get_app()
    return _app


def mint_custom(uid: str | None = None, email: str | None = None,
                name: str | None = None) -> tuple[str, str]:
    """(uid, custom_token). The browser-side sign-in needs the CUSTOM token."""
    _init()
    from firebase_admin import auth as fb

    uid = uid or (PREFIX + uuid.uuid4().hex[:8])
    email = email or f"{uid}@example.invalid"
    name = name or uid.replace(PREFIX, "").replace("_", " ").title()
    return uid, fb.create_custom_token(uid, {"email": email, "name": name}).decode()


#: Signs the page in through the product's OWN Firebase instance.
#:
#: A Google popup cannot be automated, so the alternative was to stub the browser's
#: whole auth bootstrap -- which would mean the check no longer exercises the code
#: that actually runs for a user. This does something narrower: it reaches the page's
#: existing Firebase app and calls signInWithCustomToken on it. Dynamic imports of an
#: identical URL resolve to the same cached module, so `getApp()` here IS the app
#: app.html created. The page's own `onIdTokenChanged` then fires, the gate closes and
#: polling starts, exactly as it does after a real popup.
_SIGN_IN_JS = """
async ({ token, version }) => {
  const appMod  = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-app.js`);
  const authMod = await import(`https://www.gstatic.com/firebasejs/${version}/firebase-auth.js`);
  const auth = authMod.getAuth(appMod.getApp());
  await authMod.signInWithCustomToken(auth, token);
  return auth.currentUser ? auth.currentUser.uid : null;
}
"""

SDK_VERSION = "10.12.2"


def sign_in(page, uid: str | None = None, timeout_ms: int = 30000) -> str:
    """Sign a Playwright page in as a throwaway identity. Returns the uid."""
    uid, custom = mint_custom(uid)
    page.wait_for_selector("#gate-in", timeout=timeout_ms)
    got = page.evaluate(_SIGN_IN_JS, {"token": custom, "version": SDK_VERSION})
    if got != uid:
        raise AssertionError(f"signed in as {got!r}, expected {uid!r}")
    page.wait_for_selector("#gate", state="hidden", timeout=timeout_ms)
    return uid


def mint(uid: str | None = None, email: str | None = None,
         name: str | None = None) -> str:
    """A real ID token for a test identity, valid for an hour.

    `email` is not decoration: services/auth.py rejects a token without one, because
    Google Sign-In always carries an email and a token missing it did not come from
    the flow this product offers. It rides along as a developer claim.
    """
    _init()
    from firebase_admin import auth as fb

    uid = uid or (PREFIX + uuid.uuid4().hex[:8])
    email = email or f"{uid}@example.invalid"
    name = name or uid.replace(PREFIX, "").replace("_", " ").title()

    custom = fb.create_custom_token(uid, {"email": email, "name": name})
    r = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken",
        params={"key": API_KEY},
        json={"token": custom.decode(), "returnSecureToken": True},
        timeout=60)
    if not r.ok:
        raise SystemExit(f"custom-token exchange failed: {r.status_code} {r.text[:400]}")
    return r.json()["idToken"]


def headers(uid: str | None = None) -> dict[str, str]:
    return {"Authorization": "Bearer " + mint(uid)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--uid", default=None, help="test identity to mint for")
    ap.add_argument("--check", default=None,
                    help="base URL: call /api/me with the token and print the answer")
    args = ap.parse_args()

    token = mint(args.uid)
    if args.check:
        me = requests.get(args.check.rstrip("/") + "/api/me",
                          headers={"Authorization": "Bearer " + token}, timeout=60)
        print(f"/api/me -> {me.status_code} {me.text[:300]}")
        return 0 if me.ok else 1
    print(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
