"""Set up Google Sign-In for this project, as far as an API can.

Firebase Auth is mostly a console product, but three of the four steps are REST calls,
and doing them here means the setup is reviewable and repeatable rather than a
half-remembered click path. Run it, then finish the one step that genuinely needs the
console (it provisions an OAuth client, which has no public API).

    python scripts\\setup_auth.py gen-lang-client-0955694243

Reads its credentials from `gcloud auth print-access-token`. Idempotent: every call
either creates the thing or reports that it already exists.
"""

from __future__ import annotations

import json
import subprocess
import sys

import requests

FIREBASE = "https://firebase.googleapis.com/v1beta1"
IDENTITY = "https://identitytoolkit.googleapis.com/admin/v2"
APP_NAME = "Challenge Accepted web"


def _p(s: str) -> None:
    print(s.encode("ascii", "replace").decode("ascii"), flush=True)


def token() -> str:
    out = subprocess.run(["gcloud", "auth", "print-access-token"],
                         capture_output=True, text=True, shell=True)
    if out.returncode != 0:
        raise SystemExit("gcloud auth print-access-token failed:\n" + out.stderr)
    return out.stdout.strip()


def main() -> int:
    if len(sys.argv) < 2:
        _p("usage: setup_auth.py <project_id>")
        return 2
    project = sys.argv[1]
    # `x-goog-user-project` is not optional here. With a user's ADC and no quota
    # project, firebase.googleapis.com returns 403 SERVICE_DISABLED -- which reads as
    # "the API is off" and sends you to enable an API that is already enabled.
    h = {"Authorization": f"Bearer {token()}", "x-goog-user-project": project}

    # --- 1. is this a Firebase project at all? ------------------------------------
    r = requests.get(f"{FIREBASE}/projects/{project}", headers=h, timeout=60)
    if r.status_code == 404:
        # Adding Firebase to an existing GCP project IS an API call, despite every
        # guide describing it as a console click. Doing it here keeps the whole setup
        # in one reviewable place.
        _p("Adding Firebase to the project...")
        add = requests.post(f"{FIREBASE}/projects/{project}:addFirebase",
                            headers=h, json={}, timeout=180)
        if not add.ok:
            _p(f"  failed: {add.status_code} {add.text[:400]}")
            return 1
        for _ in range(30):
            r = requests.get(f"{FIREBASE}/projects/{project}", headers=h, timeout=60)
            if r.ok:
                break
    if not r.ok:
        _p(f"Cannot read the Firebase project ({r.status_code}):")
        _p("  " + r.text[:400])
        _p(f"\n  If it says NOT_FOUND, add Firebase to this project once at")
        _p(f"  https://console.firebase.google.com/ -> Add project -> choose the")
        _p(f"  EXISTING Google Cloud project '{project}'. Then re-run this.")
        return 1
    _p(f"Firebase project : {r.json().get('displayName') or project}")

    # --- 2. a web app, which is what carries the browser config -------------------
    apps = requests.get(f"{FIREBASE}/projects/{project}/webApps",
                        headers=h, timeout=60).json().get("apps", [])
    app = next((a for a in apps if a.get("displayName") == APP_NAME), None) or \
        (apps[0] if apps else None)
    if app is None:
        _p("Creating a web app...")
        op = requests.post(f"{FIREBASE}/projects/{project}/webApps",
                           headers=h, json={"displayName": APP_NAME}, timeout=120)
        if not op.ok:
            _p(f"  failed: {op.status_code} {op.text[:300]}")
            return 1
        # The create is a long-running operation; the app shows up in the list shortly.
        for _ in range(20):
            apps = requests.get(f"{FIREBASE}/projects/{project}/webApps",
                                headers=h, timeout=60).json().get("apps", [])
            if apps:
                app = apps[0]
                break
        if app is None:
            _p("  created, but it has not appeared in the list yet -- re-run in a minute.")
            return 1
    _p(f"Web app          : {app.get('displayName')}  ({app.get('appId')})")

    cfg = requests.get(f"{FIREBASE}/{app['name']}/config", headers=h, timeout=60)
    if not cfg.ok:
        _p(f"  could not read its config: {cfg.status_code} {cfg.text[:200]}")
        return 1
    conf = cfg.json()

    # --- 3. Identity Platform config ----------------------------------------------
    ip = requests.get(f"{IDENTITY}/projects/{project}/config", headers=h, timeout=60)
    if ip.ok:
        domains = ip.json().get("authorizedDomains", [])
        _p(f"Authorized domains: {', '.join(domains) or '(none)'}")
        want = "challengeaccepted.app"
        if want not in domains:
            _p(f"Adding {want} to the authorized domains...")
            patch = requests.patch(
                f"{IDENTITY}/projects/{project}/config",
                headers=h, params={"updateMask": "authorizedDomains"},
                json={"authorizedDomains": domains + [want]}, timeout=60)
            _p("  ok" if patch.ok else f"  failed: {patch.status_code} {patch.text[:300]}")
    else:
        _p(f"Identity Platform is not initialised yet ({ip.status_code}).")

    # --- 4. the Google provider ----------------------------------------------------
    idp = requests.get(
        f"{IDENTITY}/projects/{project}/defaultSupportedIdpConfigs/google.com",
        headers=h, timeout=60)
    google_on = idp.ok and idp.json().get("enabled")
    _p(f"Google provider  : {'ENABLED' if google_on else 'not enabled'}")

    _p("\n--- what only you can do ---")
    if not google_on:
        _p("1. https://console.firebase.google.com/project/"
           f"{project}/authentication/providers")
        _p("   -> Google -> Enable -> pick a support email -> Save.")
        _p("   This provisions an OAuth client, which has no public API. It is the")
        _p("   one manual step.")
    else:
        _p("(nothing -- Google sign-in is already enabled)")

    _p("\n--- then deploy with ---")
    _p(f"  .\\deploy\\deploy.ps1 -ProjectId {project} -KeepWarm -Auth `")
    _p(f"      -FirebaseApiKey {conf.get('apiKey')} `")
    _p(f"      -FirebaseAuthDomain {conf.get('authDomain')}")
    _p("\n--- then verify from outside with ---")
    _p("  python scripts\\check_auth_live.py https://challengeaccepted.app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
