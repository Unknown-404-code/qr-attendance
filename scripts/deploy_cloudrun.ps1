# Deploy the attendance app to Google Cloud Run (free tier). See DEPLOY.md.
#
#   .\scripts\deploy_cloudrun.ps1 -Project qr-attendance-12345 -AdminEmail you@example.com
#
# Needs: gcloud signed in (gcloud auth login), billing linked to the project, and three secrets in Secret Manager:
#   database-url    the Supabase Session pooler connection string, with your database password in it
#   ga-secret       a long random string that signs logins and QR codes (keep it the same forever)
#   admin-password  the first admin's password
# The first run creates any secret that's missing (ga-secret gets a random value; the other two you fill in).
param(
    [Parameter(Mandatory = $true)][string]$Project,
    [Parameter(Mandatory = $true)][string]$AdminEmail,
    [string]$Region = "us-east1",
    [string]$Service = "attendance",
    [string]$TimeZone = "Asia/Dubai"
)
$ErrorActionPreference = "Stop"
$g = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if (-not (Test-Path $g)) { $g = "gcloud" }
$root = Split-Path $PSScriptRoot -Parent

Write-Host "Turning on Cloud Run, Cloud Build, Artifact Registry and Secret Manager ..."
& $g services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --project $Project

$existing = & $g secrets list --project $Project --format="value(name)"
foreach ($name in "database-url", "ga-secret", "admin-password") {
    if (-not ($existing -match "(^|/)$name$")) {
        Write-Host "Creating secret $name ..."
        & $g secrets create $name --replication-policy=automatic --project $Project
        if ($name -eq "ga-secret") {
            $bytes = New-Object byte[] 32
            [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
            $tmp = New-TemporaryFile
            [IO.File]::WriteAllText($tmp, [Convert]::ToBase64String($bytes).TrimEnd("=").Replace("+", "-").Replace("/", "_"))
            & $g secrets versions add ga-secret --data-file=$tmp --project $Project
            Remove-Item $tmp
        }
    }
}
foreach ($name in "database-url", "admin-password") {
    $v = & $g secrets versions list $name --project $Project --filter="state=ENABLED" --format="value(name)"
    if (-not $v) { throw "Secret '$name' has no value yet. Add one in the Google Cloud console (Secret Manager), then run this again." }
}

$number = & $g projects describe $Project --format="value(projectNumber)"
$sa = "$number-compute@developer.gserviceaccount.com"
foreach ($name in "database-url", "ga-secret", "admin-password") {
    & $g secrets add-iam-policy-binding $name --member="serviceAccount:$sa" --role="roles/secretmanager.secretAccessor" --project $Project --quiet | Out-Null
}

Write-Host "Building and deploying (the first build takes 5-10 minutes) ..."
& $g run deploy $Service --source $root --project $Project --region $Region --allow-unauthenticated `
    --port 7860 --memory 1Gi --cpu 1 --min-instances 0 --max-instances 1 --timeout 120 --cpu-boost `
    --set-env-vars "TZ=$TimeZone,ADMIN_EMAIL=$AdminEmail" `
    --set-secrets "DATABASE_URL=database-url:latest,GA_SECRET=ga-secret:latest,ADMIN_PASSWORD=admin-password:latest" `
    --quiet
& $g run services describe $Service --project $Project --region $Region --format="value(status.url)"
