"""Print an access token from Application Default Credentials.

`gcloud auth login` (the CLI session) and `gcloud auth application-default login` (ADC)
are separate credentials with separate lifetimes, and on this machine the CLI one
expires far more often. When it does, `gcloud` refuses to run while ADC is still
perfectly valid -- so a deploy blocks on a re-login that is not actually needed.

gcloud honours CLOUDSDK_AUTH_ACCESS_TOKEN. Same human, same project, same scopes;
only the plumbing differs.
"""

import google.auth
import google.auth.transport.requests

creds, _ = google.auth.default(
    scopes=["https://www.googleapis.com/auth/cloud-platform"])
creds.refresh(google.auth.transport.requests.Request())
print(creds.token)
