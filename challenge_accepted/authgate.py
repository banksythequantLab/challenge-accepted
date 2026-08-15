"""The gate every request passes through, including ADK's own routes.

There are two halves to this, and the second is the one that matters.

The first half is ordinary: reject a request with no valid Google identity.

The second half is that ADK's session endpoints take the user id **from the URL**
(`POST /apps/{app}/users/{user_id}/sessions`) and `/run_sse` takes it **from the body**.
Those ids end up in `tool_context.state["user_id"]`, which is what `save_charter` files
a challenge under and what `_group_id` derives a party from. So verifying a token and
then letting the client keep naming itself would be theatre: I could sign in as me and
create a challenge owned by you, or read a session belonging to you, with a token that
verifies perfectly. The gate therefore refuses any request whose stated user is not the
verified one.

A note on reading the body here: BaseHTTPMiddleware hands the downstream app a fresh
Request built from the same receive channel, so consuming the body would leave the
route with nothing to read. The body is replayed explicitly below. This costs one
buffer per /run_sse call and is the reason /run_sse is the only body we look at.
"""

from __future__ import annotations

import json
import re
from typing import Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .services import auth

#: Reachable without a token. Deliberately short, and every entry has a reason:
#:   /app, /favicon  -- the shell has to render before anyone can sign in
#:   /api/auth/config -- the browser needs to know WHICH project to sign in to
#:   /healthz         -- a health check that needs credentials is not a health check
_PUBLIC_EXACT = {"/app", "/healthz", "/api/healthz", "/api/auth/config", "/favicon.ico"}

#: Everything that reaches an agent, a session, or challenge data.
_GUARDED_PREFIXES = ("/api", "/run", "/run_sse", "/apps", "/list-apps", "/debug")

#: POST /apps/{app_name}/users/{user_id}/... -- ADK's session surface.
_USER_PATH = re.compile(r"^/apps/[^/]+/users/([^/]+)")

#: The bodies that name a user. Both are ADK's.
_BODY_ROUTES = {"/run", "/run_sse"}


def _needs_auth(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return False
    return any(path == p or path.startswith(p + "/") or path.startswith(p + "?")
               for p in _GUARDED_PREFIXES) or path in _BODY_ROUTES


def _deny(reason: str, status: int = 401) -> JSONResponse:
    # The reason is returned on purpose. A bare 401 during a live demo tells the
    # person holding the laptop nothing, and these reasons leak nothing: they describe
    # the caller's own request.
    return JSONResponse({"detail": reason}, status_code=status,
                        headers={"WWW-Authenticate": "Bearer"})


def install(app) -> None:
    """Attach the gate. A no-op when CA_AUTH is not 'required'."""

    @app.middleware("http")
    async def enforce_identity(request: Request, call_next: Callable):
        if not auth.required() or request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if not _needs_auth(path):
            return await call_next(request)

        try:
            caller = auth.verify(request.headers.get("Authorization"))
        except auth.AuthError as exc:
            return _deny(f"Sign in with Google to use Challenge Accepted ({exc})")

        # --- the client does not get to name itself --------------------------------
        m = _USER_PATH.match(path)
        if m and m.group(1) != caller.uid:
            return _deny(
                f"This session belongs to another account. You are signed in as "
                f"{caller.display}.", status=403)

        if path in _BODY_ROUTES and request.method == "POST":
            body = await request.body()

            async def replay():
                return {"type": "http.request", "body": body, "more_body": False}

            request._receive = replay  # noqa: SLF001 -- see the module docstring
            try:
                stated = (json.loads(body or b"{}") or {}).get("userId")
            except ValueError:
                return _deny("Request body is not valid JSON", status=400)
            if stated and stated != caller.uid:
                return _deny(
                    f"Refusing to run as {stated}: you are signed in as "
                    f"{caller.display}.", status=403)

        request.state.caller = caller
        return await call_next(request)


def current(request: Request) -> auth.Caller:
    """FastAPI dependency: the verified caller.

    With auth off this returns a Caller built from nothing, so local development and
    the offline checks keep working -- and every ownership check downstream then
    trivially passes, which is exactly what `CA_AUTH=off` means and why /healthz says
    so out loud.
    """
    caller = getattr(request.state, "caller", None)
    if caller is not None:
        return caller
    if not auth.required():
        return auth.Caller(uid="local", name="Local user")
    raise HTTPException(status_code=401, detail="Not signed in")
