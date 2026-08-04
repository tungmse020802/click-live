# Click Live desktop-tool - run on Windows
# scripts\run-windows.bat

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

function Invoke-External {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command
  )

  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try {
    $output = & $Command 2>&1
    foreach ($line in @($output)) {
      if ($null -eq $line) { continue }
      $text = if ($line -is [System.Management.Automation.ErrorRecord]) {
        $line.ToString()
      } else {
        [string]$line
      }
      if ($text) {
        Write-Host "  $text"
      }
    }
    return $LASTEXITCODE
  } finally {
    $ErrorActionPreference = $prev
  }
}

function Get-DesktopToolDir {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  }
  return (Resolve-Path (Join-Path $scriptDir "..")).Path
}

function Stop-ClickLive {
  Write-Step "1/5 Stop old processes"
  $selfPid = $PID

  foreach ($line in (& netstat -aon 2>$null | Select-String ":8795" | Select-String "LISTENING")) {
    $parts = ($line -split '\s+') | Where-Object { $_ -ne '' }
    $procId = $parts[-1]
    if ($procId -match '^\d+$') {
      $pidNum = [int]$procId
      if ($pidNum -eq $selfPid) { continue }
      Write-Host "  stop PID $pidNum (port 8795)"
      Stop-Process -Id $pidNum -Force -ErrorAction SilentlyContinue
    }
  }

  Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object {
      if ($_.ProcessId -eq $selfPid) { return $false }
      if ($_.Name -eq 'electron.exe') {
        return $_.CommandLine -match 'desktop-tool|click-live-desktop-tool'
      }
      if ($_.Name -eq 'node.exe') {
        return $_.CommandLine -match 'desktop-tool|click-live-desktop-tool|electron'
      }
      if ($_.Name -eq 'powershell.exe') {
        return $_.CommandLine -match 'windows-click-helper\.ps1'
      }
      return $false
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

  Write-Step "2/5 git pull"

  if (-not (Test-Cmd git)) {
    Write-Warn "git not found - skip pull"
    return
  }
  if (-not (Test-Path (Join-Path $Root ".git"))) {
    Write-Warn "not a git repo - skip pull"
    return
  }

  Push-Location $Root
  try {
    $branch = (& git rev-parse --abbrev-ref HEAD 2>$null).Trim()
    if (-not $branch -or $branch -eq "HEAD") {
      $branch = "feature/pipeline-optimize"
    }
    Write-Host "  branch: $branch"
    Invoke-External { git fetch origin } | Out-Null
    $pullCode = Invoke-External { git pull --ff-only origin $branch }
    if ($pullCode -ne 0) {
      Write-Warn "git pull failed - continuing with local code"
    } else {
      Write-Host "  OK"
    }
  } finally {
    Pop-Location
  }
}

function Test-NodeJs {
  Write-Step "3/5 Check Node.js"

  if (-not (Test-Cmd node)) {
    throw "Node.js not found. Run scripts\install-windows.bat or install from https://nodejs.org"
  }
  if (-not (Test-Cmd npm)) {
    throw "npm not found. Reinstall Node.js LTS from https://nodejs.org"
  }

  Write-Host "  OK Node.js $(node -v)"
  Write-Host "  OK npm $(npm -v)"
}

function Ensure-EnvFile {
  param([string]$DesktopToolDir)

  Write-Step "4/5 Configure .env"

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
}

function Install-NpmDeps {
  param(
    [string]$DesktopToolDir,
    [bool]$AfterPull = $false
  )

  $electronPkg = Join-Path $DesktopToolDir "node_modules\electron\package.json"
  $koffiPkg = Join-Path $DesktopToolDir "node_modules\koffi\package.json"
  $lockFile = Join-Path $DesktopToolDir "package-lock.json"
  $nodeModules = Join-Path $DesktopToolDir "node_modules"

  $needsInstall = (-not (Test-Path $electronPkg)) -or (-not (Test-Path $koffiPkg))
  if (-not $needsInstall -and $AfterPull -and (Test-Path $lockFile) -and (Test-Path $nodeModules)) {
    if ((Get-Item $lockFile).LastWriteTime -gt (Get-Item $nodeModules).LastWriteTime) {
      $needsInstall = $true
    }
  }

  if (-not $needsInstall) {
    Write-Host "  OK node_modules (skip npm install)"
    return
  }

  Write-Host "  npm install ..."
  Push-Location $DesktopToolDir
  try {
    $code = Invoke-External { npm install }
    if ($code -ne 0) {
      throw "npm install failed with code $code"
    }
    Write-Host "  OK"
  } finally {
    Pop-Location
  }
}

function Start-DesktopTool {
  param([string]$DesktopToolDir)

  Write-Step "5/5 Start desktop-tool"
  Write-Host "  Click: PowerShell helper"
  Write-Host "  Health: http://127.0.0.1:8795/health"
  Write-Host ""

  Push-Location $DesktopToolDir
  try {
    $code = Invoke-External { npm start }
    if ($code -ne 0) {
      throw "npm start failed with code $code"
    }
  } finally {
    Pop-Location
  }
}

$exitCode = 0
$desktopToolDir = Get-DesktopToolDir
$repoRoot = (Resolve-Path (Join-Path $desktopToolDir "..")).Path

try {
  Write-Host ""
  Write-Host "Click Live desktop-tool" -ForegroundColor Green
  Write-Host "Folder: $desktopToolDir"
  Write-Host ""

  Stop-ClickLive

  $didPull = $false
  if (-not $SkipPull) {
    Update-Repo -Root $repoRoot
    $didPull = $true
  } else {
    Write-Host ""
    Write-Host "==> 2/5 git pull (skipped)" -ForegroundColor Cyan
  }

  Test-NodeJs
  Ensure-EnvFile -DesktopToolDir $desktopToolDir

  Write-Host ""
  Write-Host "==> npm deps" -ForegroundColor Cyan
  Install-NpmDeps -DesktopToolDir $desktopToolDir -AfterPull:$didPull

  if (-not $SkipStart) {
    Start-DesktopTool -DesktopToolDir $desktopToolDir
  } else {
    Write-Host ""
    Write-Host "Skip start (-SkipStart)" -ForegroundColor Yellow
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
