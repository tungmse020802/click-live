# Click Live desktop-tool - Windows install
# Run: scripts\install-windows.bat

param(
  [string]$RepoUrl = "https://github.com/tungmse020802/click-live.git",
  [string]$Branch = "feature/pipeline-optimize",
  [string]$InstallRoot = "$env:USERPROFILE\click-live",
  [string]$QueueUrl = "http://160.30.19.215:8787",
  [string]$PullToken = "",
  [switch]$SkipClone,
  [switch]$ForceClone,
  [switch]$SkipStart
)

$ErrorActionPreference = "Continue"

function Write-Step {
  param([string]$Message)
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
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
    Write-Host "  ! winget missing - skip $Label" -ForegroundColor Yellow
    return
  }

  if (Test-WingetInstalled -Id $Id) {
    Write-Host "  OK $Label already installed"
    return
  }

  Write-Host "  Installing $Label ..."
  & winget install --id $Id -e --accept-source-agreements --accept-package-agreements
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) {
    Write-Host "  ! winget returned $LASTEXITCODE for $Label" -ForegroundColor Yellow
  }
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
  Ensure-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS"
  Add-ToPath "$env:ProgramFiles\nodejs"
  Add-ToPath "${env:ProgramFiles(x86)}\nodejs"

  if (-not (Test-Cmd node)) {
    throw "Node.js not found. Install from https://nodejs.org then rerun."
  }
  Write-Host "  OK Node.js $(node -v)"
}

function Ensure-Git {
  if (Test-Cmd git) {
    Write-Host "  OK $(git --version)"
    return
  }

  Write-Step "Install Git"
  Ensure-WingetPackage -Id "Git.Git" -Label "Git"
  Add-ToPath "$env:ProgramFiles\Git\cmd"
  Add-ToPath "${env:ProgramFiles(x86)}\Git\cmd"

  if (-not (Test-Cmd git)) {
    throw "Git not found. Install from https://git-scm.com/download/win"
  }
  Write-Host "  OK $(git --version)"
}

function Ensure-Chrome {
  $paths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  foreach ($p in $paths) {
    if (Test-Path $p) {
      Write-Host "  OK Chrome: $p"
      return
    }
  }
  Write-Host "  ! Chrome not found - trying winget ..." -ForegroundColor Yellow
  Ensure-WingetPackage -Id "Google.Chrome" -Label "Google Chrome"
}

function Ensure-Repo {
  param(
    [string]$Root,
    [string]$Url,
    [string]$GitBranch
  )

  if (Test-Path (Join-Path $Root ".git")) {
    Write-Step "Update repo at $Root"
    Push-Location $Root
    & git fetch origin
    & git checkout $GitBranch
    if ($LASTEXITCODE -ne 0) {
      Pop-Location
      throw "git checkout failed for branch $GitBranch"
    }
    & git pull origin $GitBranch
    Pop-Location
    return
  }

  Write-Step "Clone repo"
  New-Item -ItemType Directory -Force -Path $Root | Out-Null
  & git clone --branch $GitBranch --single-branch $Url $Root
  if ($LASTEXITCODE -ne 0) {
    throw "git clone failed - check network or branch $GitBranch"
  }
}

function Ensure-EnvFile {
  param(
    [string]$DesktopToolDir,
    [string]$Queue,
    [string]$Token
  )

  $envFile = Join-Path $DesktopToolDir ".env"
  $example = Join-Path $DesktopToolDir ".env.example"
  if (-not (Test-Path $example)) {
    throw ".env.example not found in $DesktopToolDir"
  }

  if (-not (Test-Path $envFile)) {
    Copy-Item $example $envFile
    Write-Host "  Created .env from .env.example"
  }

  $lines = Get-Content $envFile
  $out = @()
  foreach ($line in $lines) {
    if ($line -match '^\s*DESKTOP_TOOL_QUEUE_URL=') {
      $out += "DESKTOP_TOOL_QUEUE_URL=$Queue"
    } elseif ($line -match '^\s*DESKTOP_TOOL_PULL_TOKEN=') {
      if ($Token) {
        $out += "DESKTOP_TOOL_PULL_TOKEN=$Token"
      } else {
        $out += $line
      }
    } else {
      $out += $line
    }
  }
  Set-Content -Path $envFile -Value $out -Encoding ASCII

  if (-not $Token) {
    $tokenLine = $out | Where-Object { $_ -match '^\s*DESKTOP_TOOL_PULL_TOKEN=' } | Select-Object -First 1
    if ($tokenLine -match '^\s*DESKTOP_TOOL_PULL_TOKEN=\s*$') {
      Write-Host ""
      Write-Host "Enter DESKTOP_PULL_TOKEN from server telegram_bot/.env:" -ForegroundColor Yellow
      $typed = Read-Host "DESKTOP_TOOL_PULL_TOKEN"
      if ($typed) {
        $fixed = @()
        foreach ($line in $out) {
          if ($line -match '^\s*DESKTOP_TOOL_PULL_TOKEN=') {
            $fixed += "DESKTOP_TOOL_PULL_TOKEN=$typed"
          } else {
            $fixed += $line
          }
        }
        Set-Content -Path $envFile -Value $fixed -Encoding ASCII
      } else {
        Write-Host "  ! No token - app runs but will not poll queue." -ForegroundColor Yellow
      }
    }
  }

  Write-Host "  OK .env: $envFile"
}

function New-RunShortcut {
  param([string]$DesktopToolDir)

  $runBat = Join-Path $DesktopToolDir "scripts\run-windows.bat"
  if (-not (Test-Path $runBat)) { return }

  try {
    $desktop = [Environment]::GetFolderPath("Desktop")
    $shortcutPath = Join-Path $desktop "Click Live Desktop Tool.lnk"
    $wsh = New-Object -ComObject WScript.Shell
    $sc = $wsh.CreateShortcut($shortcutPath)
    $sc.TargetPath = $runBat
    $sc.WorkingDirectory = $DesktopToolDir
    $sc.WindowStyle = 1
    $sc.Description = "Click Live desktop-tool"
    $sc.Save()
    Write-Host "  OK shortcut: $shortcutPath"
  } catch {
    Write-Host "  ! shortcut skipped: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

function Get-DesktopToolDir {
  $scriptDir = $PSScriptRoot
  if (-not $scriptDir) {
    $scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
  }

  $parent = Join-Path $scriptDir ".."
  $resolved = Resolve-Path $parent -ErrorAction SilentlyContinue
  if ($resolved) {
    $localDir = $resolved.Path
    $pkg = Join-Path $localDir "package.json"
    if ((Test-Path $pkg) -and (-not $ForceClone)) {
      Write-Host "  OK use current folder: $localDir"
      return $localDir
    }
  }

  if ($SkipClone) {
    $dt = Join-Path $InstallRoot "desktop-tool"
    if (Test-Path (Join-Path $dt "package.json")) {
      return $dt
    }
  }

  Ensure-Repo -Root $InstallRoot -Url $RepoUrl -GitBranch $Branch
  return (Join-Path $InstallRoot "desktop-tool")
}

$exitCode = 0
$dirPushed = $false

try {
  Write-Host ""
  Write-Host "Click Live - install desktop-tool on Windows" -ForegroundColor Green
  Write-Host "Repo: $RepoUrl"
  Write-Host "Branch: $Branch"

  Write-Step "Check dependencies"
  Ensure-Git
  Ensure-NodeJs
  Ensure-Chrome

  Write-Step "Prepare source"
  $desktopToolDir = Get-DesktopToolDir
  $pkgJson = Join-Path $desktopToolDir "package.json"
  if (-not (Test-Path $pkgJson)) {
    throw "desktop-tool not found at $desktopToolDir"
  }

  Write-Step "Configure .env"
  Ensure-EnvFile -DesktopToolDir $desktopToolDir -Queue $QueueUrl -Token $PullToken

  Write-Step "npm install"
  Push-Location $desktopToolDir
  $dirPushed = $true

  & npm install
  if ($LASTEXITCODE -ne 0) {
    throw "npm install failed with code $LASTEXITCODE"
  }

  Write-Step "Syntax check"
  & npm run check
  if ($LASTEXITCODE -ne 0) {
    throw "npm run check failed with code $LASTEXITCODE"
  }

  New-RunShortcut -DesktopToolDir $desktopToolDir

  Write-Host ""
  Write-Host "Install complete." -ForegroundColor Green
  Write-Host "  Folder : $desktopToolDir"
  Write-Host "  Run    : scripts\run-windows.bat"
  Write-Host "  Health : http://127.0.0.1:8795/health"
  Write-Host ""

  if (-not $SkipStart) {
    Write-Step "Start desktop-tool"
    & npm start
    if ($LASTEXITCODE -ne 0) {
      throw "npm start failed with code $LASTEXITCODE"
    }
  }
} catch {
  Write-Err $_.Exception.Message
  if ($_.ScriptStackTrace) {
    Write-Host $_.ScriptStackTrace -ForegroundColor DarkGray
  }
  $exitCode = 1
} finally {
  if ($dirPushed) {
    Pop-Location -ErrorAction SilentlyContinue
  }
}

exit $exitCode
