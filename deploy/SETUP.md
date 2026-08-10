# Cloud setup

Two steps need a browser, so they can't be automated. Everything after them is scripted.

## What's already done

- **gcloud CLI 579.0.0** installed at `B:\tools\google-cloud-sdk` and added to your
  User PATH. Open a **new** terminal and `gcloud version` works.
- You're already credentialed as `dj@soltis.info` from a previous gcloud config, and
  Application Default Credentials exist at `%APPDATA%\gcloud\application_default_credentials.json`.

**Install note, so nobody repeats the hunt:** neither `google-cloud-sdk.zip` nor
`google-cloud-sdk-windows-x86_64-bundled-python.zip` contains a single `.cmd` file, and
`install.bat` exits without generating them. The SDK is fine — `lib\gcloud.py` runs
correctly under the bundled interpreter — it just ships with no Windows launcher.
`bin\gcloud.cmd` was written by hand; see the comment in that file. (`google-cloud-cli-*`
filenames are 404 — the archives are still named `google-cloud-sdk-*`.)

## Step 1 — refresh your login (browser)

Your stored tokens have expired: `Reauthentication failed. cannot prompt during
non-interactive execution.` Run both, in a new terminal:

```powershell
gcloud auth login
gcloud auth application-default login
```

The second one is not optional. `gcloud auth login` authenticates the *CLI*;
Application Default Credentials are what the **Firestore Python client** uses. Skipping
it is the classic way to get a deploy that works from your terminal and a running app
that silently falls back to the in-memory store.

## Step 2 — pick the project

```powershell
gcloud projects list
gcloud config set project <PROJECT_ID>
```

Note the Gemini key you used locally belongs to project **836107021848**. Using the same
project for Cloud Run and Firestore keeps billing and quota in one place.

## Step 3 — deploy (scripted)

```powershell
cd B:\microgoals
.\deploy\deploy.ps1 -ProjectId <PROJECT_ID> -KeepWarm
```

This enables the APIs, creates the Firestore database only if it's absent, and deploys a
single Cloud Run service serving both the agent API and the dashboard.

`-KeepWarm` sets `min-instances=1`. Use it from the day you start rehearsing — a cold
start is several seconds of dead air in a four-minute video.

## Step 4 — verify Firestore actually engaged

```powershell
curl https://<service-url>/healthz
```

Expect `"store":"firestore"`. **If it says `"memory"`, stop and fix it.** The app is
designed to keep serving rather than crash, so a broken Firestore config looks perfectly
healthy while losing every write on restart and giving each Cloud Run instance its own
private dict — no persistence, no multiplayer, no error message. The container logs will
carry an explicit `FALLING BACK TO IN-MEMORY STORE` error.

Usual cause: the runtime service account lacks `roles/datastore.user`.

```powershell
$svc = gcloud run services describe microgoals --region us-central1 --format "value(spec.template.spec.serviceAccountName)"
gcloud projects add-iam-policy-binding <PROJECT_ID> --member "serviceAccount:$svc" --role roles/datastore.user
```

To make a misconfigured deploy fail loudly instead of degrading, add
`CA_REQUIRE_FIRESTORE=1` to the service's env vars.

## Step 5 — the multiplayer demo beat

Once `/healthz` reports `firestore`, two browser windows finally see the same data.
That's the clip worth recording:

1. Window A: run a challenge to the point where a blocker surfaces.
2. Window B: open `/app` as a teammate.
3. B's Coach opens with *"Derek found Cloud Run requires billing enabled..."* and hands
   them a step nobody has taken.

Verified locally end to end via `scripts\live_group.py`; what Firestore adds is that the
two windows are genuinely separate processes.
