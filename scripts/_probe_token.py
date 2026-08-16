import sys
import google.auth
import google.auth.transport.requests as gart
import requests

creds, proj = google.auth.default()
creds.refresh(gart.Request())
who = requests.get("https://www.googleapis.com/oauth2/v3/userinfo",
                   headers={"Authorization": f"Bearer {creds.token}"}, timeout=30)
print("ADC project:", proj)
print("ADC identity:", who.text.strip()[:200] if who.ok else f"{who.status_code} {who.text[:200]}")
print("ADC type:", type(creds).__name__)

import firebase_admin
from firebase_admin import auth

firebase_admin.initialize_app(options={
    "projectId": "gen-lang-client-0955694243",
    "serviceAccountId": "firebase-adminsdk-fbsvc@gen-lang-client-0955694243.iam.gserviceaccount.com",
})
try:
    t = auth.create_custom_token("probe_uid", {"email": "probe@example.com"})
    print("OK custom token, length", len(t))
except Exception as e:
    print("FAILED:", type(e).__name__, str(e)[:300])
    sys.exit(1)
