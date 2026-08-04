# Click Live desktop-tool — setup all-in-one + run
# Called by scripts\run-windows.bat

param(
  [switch]$SkipPull,
  [switch]$SkipStart
)

$ErrorActionPreference = "Stop"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Warn {
  param([string]$Message)
  Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Write-Err {
  param([string]$Message)
  Write-Host "[ERROR] $Message" -ForegroundColor Red
}

function Test-Cmd {
  param([string]$Name)
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Test-WingetInstalled {
  param([string]$Id)
  if (-not (Test-Cmd winget)) { return $false }
  $out = & winget list --id $Id --accept-source-agreements 2>&1
  if ($LASTEXITCODE -ne 0) { return $false }
  return [bool]($out | Select-String -SimpleMatch $Id -Quiet)
}

function Ensure-WingetPackage {
  param(
    [Parameter(Mandatory = $true)][string]$Id,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if (-not (Test-Cmd winget)) {
    Write-Warn "winget missing — skip auto-install $Label"
    return $false
  }

  if (Test-WingetInstalled -Id $Id) {
    Write-Host "  OK $Label"
    return $true
  }

  Write-Host "  Installing $Label ..."
  & winget install --id $Id -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
    Write-Warn "winget returned $LASTEXITCODE for $Label"
    return $false
  }
  return $true
}

function Add-ToPath {
  param([string]$Dir)
  if ($Dir -and (Test-Path $Dir) -and ($env:Path -notlike "*$Dir*")) {
    $env:Path = "$Dir;$env:Path"
  }
}

function Ensure-NodeJs {
  if (Test-Cmd node) {
    Write-Host "  OK Node.js $(node -v)"
    return
  }

  Write-Step "Install Node.js LTS"
  Ensure-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS" | Out-Null
  Add-ToPath "$env:ProgramFiles\nodejs"
  Add-ToPath "${env:ProgramFiles(x86)}\nodejs"

  if (-not (Test-Cmd node)) {
    throw "Node.js not found. Install from https://nodejs.org then rerun scripts\run-windows.bat"
  }
  Write-Host "  OK Node.js $(node -v)"
}

function Ensure-Git {
  if (Test-Cmd git) {
    Write-Host "  OK $(git --version)"
    return
  }

  Write-Step "Install Git"
  Ensure-WingetPackage -Id "Git.Git" -Label "Git" | Out-Null
  Add-ToPath "$env:ProgramFiles\Git\cmd"
  Add-ToPath "${env:ProgramFiles(x86)}\Git\cmd"

  if (-not (Test-Cmd git)) {
    throw "Git not found. Install from https://git-scm.com/download/win"
  }
  Write-Host "  OK $(git --version)"
}

function Ensure-Go {
  if (Test-Cmd go) {
    Write-Host "  OK $(go version)"
    return $true
  }

  Write-Step "Install Go (build click-helper.exe)"
  Ensure-WingetPackage -Id "GoLang.Go" -Label "Go" | Out-Null
  Add-ToPath "$env:ProgramFiles\Go\bin"
  Add-ToPath "${env:UserProfile}\go\bin"

  if (-not (Test-Cmd go)) {
    Write-Warn "Go not found — app will use PowerShell click helper fallback"
    return $false
  }
  Write-Host "  OK $(go version)"
  return $true
}

function Stop-ClickLive {
  Write-Step "Stop old processes"

  foreach ($line in (& netstat -aon 2>$null | Select-String ":8795" | Select-String "LISTENING")) {
    $parts = ($line -split '\s+') | Where-Object { $_ -ne '' }
    $procId = $parts[-1]
    if ($procId -match '^\d+$') {
      Write-Host "  stop PID $procId (port 8795)"
      Stop-Process -Id ([int]$procId) -Force -ErrorAction SilentlyContinue
    }
  }

  $pat = 'desktop-tool|click-live-desktop-tool|click-helper\.exe|windows-click-helper'
  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      ($_.Name -in @('electron.exe', 'node.exe', 'powershell.exe', 'click-helper.exe')) -and
      ($_.CommandLine -match $pat)
    } |
    ForEach-Object {
      Write-Host "  stop PID $($_.ProcessId) $($_.Name)"
      Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }

  Start-Sleep -Seconds 1
  Write-Host "  OK"
}

function Update-Repo {
  param([string]$Root)

  if (-not (Test-Cmd git)) { return }
  if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Warn "Not a git repo — skip pull"
    return
  }

  Write-Step "git pull"
  Push-Location $Root
  try {
    $branch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if (-not $branch -or $branch -eq "HEAD") {
      $branch = "feature/pipeline-optimize"
    }
    Write-Host "  branch: $branch"
    & git fetch origin 2>&1 | ForEach-Object { Write-Host "  $_" }
    & git pull --ff-only origin $branch 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
      Write-Warn "git pull failed — continuing with local code"
    }
  } finally {
    Pop-Location
  }
}

function Ensure-EnvFile {
  param([string]$DesktopToolDir)

  $envFile = Join-Path $DesktopToolDir ".env"
  $example = Join-Path $DesktopToolDir ".env.example"

  if (-not (Test-Path $envFile)) {
    if (-not (Test-Path $example)) {
      throw ".env.example not found in $DesktopToolDir"
    }
    Copy-Item $example $envFile
    Write-Host "  Created .env from .env.example"
  } else {
    Write-Host "  OK .env exists"
  }
  Write-Host "  Login user trong app UI (khong can pull token trong .env)"
}

function Install-NpmDeps {
  param([string]$DesktopToolDir)

  Write-Step "npm install"
  Push-Location $DesktopToolDir
  try {
    & npm install
    if ($LASTEXITCODE -ne 0) {
      throw "npm install failed with code $LASTEXITCODE"
    }
    Write-Host "  OK"
  } finally {
    Pop-Location
  }
}

function Build-ClickHelper {
  param(
    [string]$DesktopToolDir,
    [bool]$GoReady
  )

  Write-Step "Build click-helper.exe (native click process)"

  $outDir = Join-Path $DesktopToolDir "resources\bin\win32"
  $out = Join-Path $outDir "click-helper.exe"
  $src = Join-Path $DesktopToolDir "click-helper"

  New-Item -ItemType Directory -Force -Path $outDir | Out-Null

  if (-not $GoReady) {
    Write-Warn "No Go — skip native helper; PowerShell fallback will be used"
    return
  }

  if (-not (Test-Path (Join-Path $src "main.go"))) {
    Write-Warn "click-helper source missing — skip build"
    return
  }

  Push-Location $src
  try {
    Write-Host "  go build ..."
    & go build -trimpath -ldflags="-s -w" -o $out .
    if ($LASTEXITCODE -ne 0) {
      throw "go build failed with code $LASTEXITCODE"
    }
    $size = (Get-Item $out).Length
    Write-Host "  OK $out ($([math]::Round($size / 1KB)) KB)"
  } finally {
    Pop-Location
  }
}

function Test-Syntax {
  param([string]$DesktopToolDir)

  Write-Step "Syntax check"
  Push-Location $DesktopToolDir
  try {
    & npm run check 2>&1 | ForEach-Object { Write-Host "  $_" }
    if ($LASTEXITCODE -ne 0) {
      Write-Warn "npm run check failed — continuing anyway"
    } else {
      Write-Host "  OK"
    }
  } finally {
    Pop-Location
  }
}

function Start-DesktopTool {
  param([string]$DesktopToolDir)

  Write-Step "Start desktop-tool"
  Write-Host "  Health: http://127.0.0.1:8795/health"
  Write-Host "  Click log: desktop-tool\logs (or userData\logs khi cai app)"
  Write-Host ""

  Push-Location $DesktopToolDir
  try {
    & npm start
    if ($LASTEXITCODE -ne 0) {
      throw "npm start failed with code $LASTEXITCODE"
    }
  } finally {
    Pop-Location
  }
}

function Get-DesktopToolDir {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  }
  return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

$exitCode = 0

try {
  [Console]::OutputEncoding = [System.Text.Encoding]::UTF8

  Write-Host ""
  Write-Host "========================================" -ForegroundColor Green
  Write-Host " Click Live desktop-tool — setup + run" -ForegroundColor Green
  Write-Host "========================================" -ForegroundColor Green

  $desktopToolDir = Get-DesktopToolDir
  $repoRoot = (Resolve-Path (Join-Path $desktopToolDir "..")).Path

  Write-Step "Check dependencies"
  Ensure-Git
  Ensure-NodeJs
  $goReady = Ensure-Go

  Stop-ClickLive

  if (-not $SkipPull) {
    Update-Repo -Root $repoRoot
  }

  Write-Step "Configure .env"
  Ensure-EnvFile -DesktopToolDir $desktopToolDir

  Install-NpmDeps -DesktopToolDir $desktopToolDir
  Build-ClickHelper -DesktopToolDir $desktopToolDir -GoReady $goReady
  Test-Syntax -DesktopToolDir $desktopToolDir

  Write-Host ""
  Write-Host "Setup complete." -ForegroundColor Green
  Write-Host "  Folder : $desktopToolDir"
  if (Test-Path (Join-Path $desktopToolDir "resources\bin\win32\click-helper.exe")) {
    Write-Host "  Click  : native click-helper.exe"
  } else {
    Write-Host "  Click  : PowerShell helper (fallback)"
  }
  Write-Host ""

  if (-not $SkipStart) {
    Start-DesktopTool -DesktopToolDir $desktopToolDir
  }
} catch {
  Write-Err $_.Exception.Message
  if ($_.ScriptStackTrace) {
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
  }
  $exitCode = 1
}

if ($exitCode -ne 0) {
  Write-Host ""
  Read-Host "Press Enter to close"
}

exit $exitCode
