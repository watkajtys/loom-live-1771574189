# Project Loom Deployment Helper (Windows PowerShell)
# Usage: .\deploy_vps.ps1 user@vps-ip /path/to/destination

param (
    [Parameter(Mandatory=$true)]
    [string]$Remote,
    [Parameter(Mandatory=$true)]
    [string]$Dest
)

Write-Host "--- Preparing Loom for Remote Deployment ---" -ForegroundColor Cyan

# Exclude large and unnecessary directories
# Note: scp doesn't support exclusions easily, so we'll use a temporary archive or simple copy
$Excludes = @(
    ".git",
    "__pycache__",
    "node_modules",
    "dist",
    ".idea",
    ".vscode",
    "playwright-report",
    "test-results",
    "archive",
    "pb_data"
)

# A more robust way on Windows is to use Tar (available on Windows 10/11)
$TarFile = "loom_deploy.tar.gz"

Write-Host "--- Archiving project files (excluding unnecessary data) ---" -ForegroundColor Yellow
$TarExcludes = ""
foreach ($ex in $Excludes) {
    $TarExcludes += "--exclude='$ex' "
}

# Run tar to create deployment package
# We use bash-style excludes because windows tar (bsdtar) supports them
$TarCmd = "tar -czf $TarFile $TarExcludes ."
Invoke-Expression $TarCmd

Write-Host "--- Uploading to ${Remote}:${Dest} ---" -ForegroundColor Yellow

# Ensure destination directory exists and upload
ssh $Remote "mkdir -p $Dest"
scp $TarFile "${Remote}:${Dest}/$TarFile"

# Upload .env file explicitly if it exists
if (Test-Path ".env") {
    Write-Host "--- Syncing .env file ---" -ForegroundColor Yellow
    scp .env "${Remote}:${Dest}/.env"
} else {
    Write-Warning "No .env file found locally. You will need to create one on the server."
}

Write-Host "--- Extracting on VPS ---" -ForegroundColor Yellow
ssh $Remote "cd $Dest && tar -xzf $TarFile && rm $TarFile"

# Helpful follow-up command
Write-Host "--- Deployment Sync Complete! ---" -ForegroundColor Green
Write-Host ""
Write-Host "Run this on your VPS to start the containers:" -ForegroundColor Cyan
Write-Host "ssh $Remote 'cd $Dest && docker compose up -d --build'"
Write-Host ""
$IP = $Remote.Split('@')[-1]
Write-Host "Dashboard will be at http://$IP:8080/viewer/" -ForegroundColor Cyan

# Clean up local tar file
Remove-Item $TarFile -ErrorAction SilentlyContinue
