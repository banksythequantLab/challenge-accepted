param([string]$Freshness = "4h", [int]$Limit = 40)
$q = 'id parameter is only supported'
$filter = "resource.type=cloud_run_revision AND resource.labels.service_name=challenge-accepted AND textPayload:`"$q`""
gcloud logging read "$filter" --project gen-lang-client-0955694243 --limit $Limit --freshness $Freshness --format='value(timestamp,textPayload)'
