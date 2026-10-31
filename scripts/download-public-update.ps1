#Requires -Version 5.1
<#
.SYNOPSIS
  Download the public GitHub branch as a zip and merge into the project
  folder. Used when Git is not installed.

.PARAMETER ProjectRoot
  Absolute path to the app project root (folder with main.py).

.PARAMETER Branch
  Branch name (default: main).

.PARAMETER Owner
  GitHub account that owns the public repo.

.PARAMETER Repo
  Repository name.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $ProjectRoot,

    [string] $Branch = "main",

    [string] $Owner = "korhag",

    [string] $Repo = "total-commander-clone"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ZipUrl = "https://github.com/$Owner/$Repo/archive/refs/heads/$Branch.zip"

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Project root not found: $ProjectRoot"
}

$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("tcc-update-" + [guid]::NewGuid().ToString("N"))
$zipPath = Join-Path $tempRoot "source.zip"
$extractDir = Join-Path $tempRoot "extract"

New-Item -ItemType Directory -Path $extractDir -Force | Out-Null

Write-Host "==> Downloading public zip (no Git / no login)" -ForegroundColor Cyan
Write-Host "    $ZipUrl"
try {
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipPath -UseBasicParsing
} catch {
    throw "Download failed: $($_.Exception.Message)"
}

Write-Host "==> Extracting..." -ForegroundColor Cyan
Expand-Archive -LiteralPath $zipPath -DestinationPath $extractDir -Force

$srcRoot = Get-ChildItem -LiteralPath $extractDir -Directory | Select-Object -First 1
if (-not $srcRoot) {
    throw "Zip archive had no top-level folder."
}

Write-Host "==> Merging into project (preserving dist, .venv, local git data)..." -ForegroundColor Cyan
# Exclude build outputs, venv, local git, editor, and machine backups.
$xd = @(".git", "dist", "dist_build", ".venv", "venv", "__pycache__", ".cursor", "backup", ".idea", ".vscode")
$xf = @(".git-account.json", ".git-account.pat")

$robolog = Join-Path $tempRoot "robocopy.log"
$args = @(
    $srcRoot.FullName,
    $ProjectRoot,
    "/E",
    "/NFL", "/NDL", "/NJH", "/NJS", "/nc", "/ns", "/np",
    "/XD"
) + $xd + @("/XF") + $xf + @("/LOG:" + $robolog)

& robocopy @args | Out-Null
$rc = $LASTEXITCODE
# robocopy: 0-7 success-ish; >=8 failure
if ($rc -ge 8) {
    throw "robocopy failed with exit code $rc (see $robolog)"
}

Write-Host "    Source files updated from GitHub zip." -ForegroundColor Green

try {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
} catch {
    # ignore cleanup failures
}

exit 0
