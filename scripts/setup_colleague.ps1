#Requires -Version 5.1
<#
.SYNOPSIS
    One-shot setup for Allplan MCP Bridge on a colleague's Windows machine.
.DESCRIPTION
    1. Clones the repo (or pulls if already cloned)
    2. Runs uv sync
    3. Installs the Allplan PythonPart
    4. Writes the Claude Desktop MCP config entry
    5. Prints next steps
.EXAMPLE
    irm https://raw.githubusercontent.com/andrej-reeg/allplan-mcp-bridge/main/scripts/setup_colleague.ps1 | iex
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoUrl   = "https://github.com/andrej-reeg/allplan-mcp-bridge.git"
$RepoDir   = Join-Path $env:USERPROFILE "Documents\allplan-mcp-bridge"
$ConfigDir = Join-Path $env:APPDATA "Claude"
$ConfigFile = Join-Path $ConfigDir "claude_desktop_config.json"

function Write-Step([string]$msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-OK([string]$msg)   { Write-Host "    OK: $msg" -ForegroundColor Green }
function Write-Warn([string]$msg) { Write-Host "    WARN: $msg" -ForegroundColor Yellow }
function Write-Fail([string]$msg) { Write-Host "    FAIL: $msg" -ForegroundColor Red; exit 1 }

# ---------------------------------------------------------------------------
# 1. Check prerequisites
# ---------------------------------------------------------------------------
Write-Step "Checking prerequisites"

if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    Write-Host "    uv not found — installing via pip..." -ForegroundColor Yellow
    pip install uv | Out-Null
    if (-not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
        Write-Fail "Could not install uv. Run 'pip install uv' manually then re-run this script."
    }
}
Write-OK "uv found"

if (-not (Get-Command "git" -ErrorAction SilentlyContinue)) {
    Write-Fail "git not found. Install Git for Windows from https://git-scm.com/download/win"
}
Write-OK "git found"

# ---------------------------------------------------------------------------
# 2. Clone or update repo
# ---------------------------------------------------------------------------
Write-Step "Getting the repository"

if (Test-Path (Join-Path $RepoDir ".git")) {
    Write-Host "    Repo exists — pulling latest..." -ForegroundColor Gray
    Push-Location $RepoDir
    git pull --ff-only
    Pop-Location
    Write-OK "Repo updated: $RepoDir"
} else {
    git clone $RepoUrl $RepoDir
    Write-OK "Repo cloned: $RepoDir"
}

# ---------------------------------------------------------------------------
# 3. Install Python dependencies
# ---------------------------------------------------------------------------
Write-Step "Installing Python dependencies"
Push-Location $RepoDir
uv sync
Pop-Location
Write-OK "Dependencies installed"

# ---------------------------------------------------------------------------
# 4. Install Allplan PythonPart
# ---------------------------------------------------------------------------
Write-Step "Installing Allplan plugin"
Push-Location $RepoDir
$result = python scripts\install_pythonpart.py 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host $result
    Write-Warn "Auto-detection failed. Run manually:"
    Write-Host "    python scripts\install_pythonpart.py --scripts-dir <path> --library-dir <path>" -ForegroundColor Yellow
} else {
    Write-OK "Plugin installed"
}
Pop-Location

# ---------------------------------------------------------------------------
# 5. Configure Claude Desktop
# ---------------------------------------------------------------------------
Write-Step "Configuring Claude Desktop"

$NewEntry = @{
    command = "uv"
    args    = @("run", "python", "-m", "allplan_mcp_server")
    cwd     = $RepoDir -replace "\\", "\\"
}

if (-not (Test-Path $ConfigDir)) { New-Item -ItemType Directory -Path $ConfigDir | Out-Null }

if (Test-Path $ConfigFile) {
    $cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
} else {
    $cfg = [PSCustomObject]@{ mcpServers = [PSCustomObject]@{} }
}

if (-not $cfg.PSObject.Properties["mcpServers"]) {
    $cfg | Add-Member -MemberType NoteProperty -Name "mcpServers" -Value ([PSCustomObject]@{})
}

if ($cfg.mcpServers.PSObject.Properties["allplan"]) {
    Write-Warn "allplan entry already exists in claude_desktop_config.json — updating cwd"
    $cfg.mcpServers.allplan.cwd = $NewEntry.cwd
} else {
    $cfg.mcpServers | Add-Member -MemberType NoteProperty -Name "allplan" -Value $NewEntry
}

$cfg | ConvertTo-Json -Depth 10 | Set-Content $ConfigFile -Encoding UTF8
Write-OK "Config written: $ConfigFile"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
Write-Host @"

============================================================
  Setup complete!
============================================================

NEXT STEPS:
  1. Restart Claude Desktop.
  2. Open Allplan 2026 with any drawing.
  3. In the Library panel, find and double-click "AllplanMcpBridge".
     The palette should show: Bridge running on 127.0.0.1:49152
  4. In Claude Desktop, ask: "What Allplan tools do you have?"

IMPORTANT while Claude is working:
  - Keep the Allplan window VISIBLE (do not minimize).
  - Move your mouse over Allplan occasionally if commands are slow.
  - Do not start manual Allplan commands while Claude is executing.

Repo location: $RepoDir
Config file:   $ConfigFile
============================================================
"@ -ForegroundColor Green
