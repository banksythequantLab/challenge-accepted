"""Who is actually calling.

Until now identity was a random string the browser generated and kept in
localStorage. Every screen believed it: the party roster listed `u_9a3d0a`, the
group a challenge belonged to was whatever the client said it was, and anyone who
guessed a challenge id could read someone else's plan. That is not a small gap in a
product whose entire pitch is that a *group* works on a goal together.

This module is the one place a caller's identity is established. Everything else --
routes, tools, the store -- takes the uid from here and never from the request body.

Design notes worth keeping:

  * Google Sign-In only. No anonymous tier: an anonymous uid is the same fiction we
    just removed, wearing a server-issued costume.
  * Verification is Firebase's `verify_id_token`, which checks the signature against
    Google's rotating public keys, the audience, the issuer and the expiry. Decoding
    the JWT ourselves would check none of those and would look identical in a demo.
  * `CA_AUTH` is deliberately three-state and defaults to OFF. A silent default-on
    would break every existing check with a 401 that looks like a server fault; a
    silent default-off would let a deploy claim auth it does not have. /healthz says
    which one is live, so the claim is checkable from outside.
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import Any, Optional

from .. import config

#: "required" -- every agent and data route needs a valid Google identity.
#: "off"      -- local development and the existing offline checks.
AUTH_MODE: str = os.getenv("CA_AUTH", "off").strip().lower()

#: The Firebase project whose tokens we accept. Defaults to the GCP project, which is
#: the same thing in this deployment, but stays overridable so a staging front end can
#: point at a different auth tenant without a code change.
FIREBASE_PROJECT: str = (
    os.getenv("CA_FIREBASE_PROJECT") or config.GOOGLE_CLOUD_PROJECT or ""
)

#: Public browser config. The API key is not a secret -- it identifies the project to
#: Firebase and is visible in every Firebase web app on the internet -- but it still
#: comes from the environment rather than the repo so a fork does not ship ours.
FIREBASE_API_KEY: str = os.getenv("CA_FIREBASE_API_KEY", "")
FIREBASE_AUTH_DOMAIN: str = os.getenv("CA_FIREBASE_AUTH_DOMAIN", "")


def required() -> bool:
    return AUTH_MODE == "required"


@dataclass(frozen=True)
class Caller:
    """A verified human. Never constructed from anything a client sent us."""

    uid: str
    email: str = ""
    name: str = ""
    picture: str = ""

    @property
    def display(self) -> str:
        """What a teammate should see on the roster.

        Falls back through name -> the local part of the email -> a short uid, so the
        roster never renders an empty chip and never renders a full email address to
        the rest of the party.
        """
        if self.name:
            return self.name
        if "@" in self.email:
            return self.email.split("@", 1)[0]
        return self.uid[:8]


class AuthError(Exception):
    """Raised with the reason a token was rejected. The reason is safe to return."""


_lock = threading.Lock()
_app: Any = None
_auth_mod: Any = None


def _firebase():
    """Initialise the Admin SDK once, lazily.

    Lazily because importing firebase_admin at module scope would make the whole
    package -- and therefore the test suite and every offline check -- depend on a
    library that is only needed when auth is switched on.
    """
    global _app, _auth_mod
    if _auth_mod is not None:
        return _auth_mod
    with _lock:
        if _auth_mod is None:
            import firebase_admin
            from firebase_admin import auth as firebase_auth

            if not firebase_admin._apps:
                # Application Default Credentials on Cloud Run. projectId is passed
                # explicitly: token verification checks the audience against it, and
                # inferring it from the environment is exactly the kind of silent
                # mismatch that shows up as "invalid token" with no clue why.
                firebase_admin.initialize_app(
                    options={"projectId": FIREBASE_PROJECT} if FIREBASE_PROJECT else None
                )
            _app = firebase_admin.get_app()
            _auth_mod = firebase_auth
    return _auth_mod


def verify(bearer: Optional[str]) -> Caller:
    """Turn an `Authorization: Bearer <id_token>` header into a Caller.

    Raises AuthError with a reason a human can act on. "invalid token" alone sent a
    previous integration on a long hunt for a bug that was a clock skew.
    """
    if not bearer:
        raise AuthError("no Authorization header")
    scheme, _, token = bearer.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Authorization header is not a Bearer token")
    if not FIREBASE_PROJECT:
        raise AuthError("server has no Firebase project configured")

    try:
        claims = _firebase().verify_id_token(token.strip())
    except Exception as exc:  # firebase-admin raises a family of these
        raise AuthError(f"{type(exc).__name__}: {exc}") from exc

    uid = claims.get("uid") or claims.get("sub")
    if not uid:
        raise AuthError("token carries no uid")
    # Google Sign-In only: a token with no verified email did not come from the flow
    # this product offers, and letting it through would quietly re-open the anonymous
    # door we are closing.
    if not claims.get("email"):
        raise AuthError("token carries no email -- Google Sign-In is required")

    return Caller(
        uid=str(uid),
        email=str(claims.get("email") or ""),
        name=str(claims.get("name") or ""),
        picture=str(claims.get("picture") or ""),
    )


def browser_config() -> dict[str, Any]:
    """What /api/auth/config hands the dashboard.

    `enabled` is false when the server has no Firebase config, and the dashboard then
    runs without a sign-in gate. That combination is only legitimate locally, which is
    why /healthz reports the auth mode next to it.
    """
    ready = bool(FIREBASE_API_KEY and FIREBASE_PROJECT)
    return {
        "enabled": ready,
        "required": required(),
        "apiKey": FIREBASE_API_KEY,
        "authDomain": FIREBASE_AUTH_DOMAIN or f"{FIREBASE_PROJECT}.firebaseapp.com",
        "projectId": FIREBASE_PROJECT,
    }
