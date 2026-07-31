#Requires -Version 5.1
<#
.SYNOPSIS
  Cài Click Live desktop-tool từ đầu trên Windows (A-Z) và chạy client.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1 -PullToken "your-token-here"
#>
param(
  [string]$RepoUrl = "https://github.com/tungmse020802/click-live.git",
  [string]$Branch = "feature/pipeline-optimize",
  [string]$InstallRoot = "$env:USERPROFILE\click-live",
  [string]$QueueUrl = "http://160.30.19.215:8787",
  [string]$PullToken = "",
  [switch]$SkipClone,
  [switch]$SkipStart
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
  Write-Host ""
  Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-Command([string]$Name) {
  return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Ensure-WingetPackage {
  param(
    [Parameter(Mandatory = $true)][string]$Id,
    [Parameter(Mandatory = $true)][string]$Label
  )

  if (-not (Test-Command winget)) {
    Write-Host "  ! winget không có — bỏ qua cài $Label (cài thủ công nếu thiếu)" -ForegroundColor Yellow
    return
  }

  $installed = winget list --id $Id --accept-source-agreements 2>$null | Select-String -Pattern $Id -Quiet
  if ($installed) {
    Write-Host "  OK $Label đã có"
    return
  }

  Write-Host "  Đang cài $Label ..."
  winget install --id $Id -e --accept-source-agreements --accept-package-agreements
}

function Ensure-NodeJs {
  if (Test-Command node) {
    $ver = node -v
    Write-Host "  OK Node.js $ver"
    return
  }

  Write-Step "Cài Node.js LTS (cần cho Electron)"
  Ensure-WingetPackage -Id "OpenJS.NodeJS.LTS" -Label "Node.js LTS"

  if (-not (Test-Command node)) {
    throw "Node.js chưa sẵn sàng. Đóng/mở lại terminal rồi chạy lại script, hoặc cài từ https://nodejs.org"
  }
}

function Ensure-Git {
  if (Test-Command git) {
    Write-Host "  OK Git $(git --version)"
    return
  }

  Write-Step "Cài Git"
  Ensure-WingetPackage -Id "Git.Git" -Label "Git"

  if (-not (Test-Command git)) {
    throw "Git chưa sẵn sàng. Cài từ https://git-scm.com/download/win"
  }
}

function Ensure-Chrome {
  $chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
  )
  foreach ($p in $chromePaths) {
    if (Test-Path $p) {
      Write-Host "  OK Google Chrome: $p"
      return
    }
  }

  Write-Host "  ! Chưa thấy Google Chrome — đang thử cài qua winget ..." -ForegroundColor Yellow
  Ensure-WingetPackage -Id "Google.Chrome" -Label "Google Chrome"
}

function Ensure-Repo {
  param(
    [string]$Root,
    [string]$Url,
    [string]$GitBranch
  )

  if ($SkipClone -and (Test-Path (Join-Path $Root "desktop-tool\package.json"))) {
    Write-Host "  OK Dùng repo có sẵn: $Root"
    return
  }

  if (Test-Path (Join-Path $Root ".git")) {
    Write-Step "Cập nhật repo $Root"
    Push-Location $Root
    git fetch origin
    git checkout $GitBranch
    git pull origin $GitBranch
    Pop-Location
    return
  }

  Write-Step "Clone repo"
  New-Item -ItemType Directory -Force -Path $Root | Out-Null
  git clone --branch $GitBranch --single-branch $Url $Root
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
    throw "Không tìm thấy .env.example trong $DesktopToolDir"
  }

  if (-not (Test-Path $envFile)) {
    Copy-Item $example $envFile
    Write-Host "  Đã tạo .env từ .env.example"
  }

  $content = Get-Content $envFile -Raw
  $content = $content -replace '(?m)^DESKTOP_TOOL_QUEUE_URL=.*$', "DESKTOP_TOOL_QUEUE_URL=$Queue"

  if ($Token) {
    $content = $content -replace '(?m)^DESKTOP_TOOL_PULL_TOKEN=.*$', "DESKTOP_TOOL_PULL_TOKEN=$Token"
  } elseif ($content -match '(?m)^DESKTOP_TOOL_PULL_TOKEN=\s*$') {
    Write-Host ""
    Write-Host "Nhập DESKTOP_PULL_TOKEN (copy từ server telegram_bot/.env trên VPS):" -ForegroundColor Yellow
    $secure = Read-Host "DESKTOP_TOOL_PULL_TOKEN"
    if ($secure) {
      $content = $content -replace '(?m)^DESKTOP_TOOL_PULL_TOKEN=.*$', "DESKTOP_TOOL_PULL_TOKEN=$secure"
    } else {
      Write-Host "  ! Chưa có token — app chạy được nhưng không poll queue. Sửa .env sau." -ForegroundColor Yellow
    }
  }

  Set-Content -Path $envFile -Value $content -Encoding UTF8
  Write-Host "  OK .env tại $envFile"
}

function New-RunShortcut {
  param([string]$DesktopToolDir)

  $runBat = Join-Path $DesktopToolDir "scripts\run-windows.bat"
  if (-not (Test-Path $runBat)) { return }

  $shortcutPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "Click Live Desktop Tool.lnk"
  $wsh = New-Object -ComObject WScript.Shell
  $shortcut = $wsh.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $runBat
  $shortcut.WorkingDirectory = $DesktopToolDir
  $shortcut.WindowStyle = 1
  $shortcut.Description = "Click Live desktop-tool"
  $shortcut.Save()
  Write-Host "  OK Shortcut: $shortcutPath"
}

Write-Host ""
Write-Host "Click Live — Cài desktop-tool trên Windows" -ForegroundColor Green
Write-Host "Repo: $RepoUrl ($Branch)"

Write-Step "Kiểm tra / cài phụ thuộc"
Ensure-Git
Ensure-NodeJs
Ensure-Chrome

Write-Step "Chuẩn bị mã nguồn"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$localDesktopTool = Resolve-Path (Join-Path $scriptDir "..") -ErrorAction SilentlyContinue

if ($SkipClone -and $localDesktopTool -and (Test-Path (Join-Path $localDesktopTool "package.json"))) {
  $desktopToolDir = $localDesktopTool.Path
  Write-Host "  OK Dùng thư mục hiện tại: $desktopToolDir"
} else {
  Ensure-Repo -Root $InstallRoot -Url $RepoUrl -GitBranch $Branch
  $desktopToolDir = Join-Path $InstallRoot "desktop-tool"
}

if (-not (Test-Path (Join-Path $desktopToolDir "package.json"))) {
  throw "Không tìm thấy desktop-tool tại $desktopToolDir"
}

Write-Step "Cấu hình .env"
Ensure-EnvFile -DesktopToolDir $desktopToolDir -Queue $QueueUrl -Token $PullToken

Write-Step "npm install (Electron — có thể mất vài phút lần đầu)"
Push-Location $desktopToolDir
npm install
if ($LASTEXITCODE -ne 0) {
  Pop-Location
  throw "npm install thất bại"
}

Write-Step "Kiểm tra syntax"
npm run check
if ($LASTEXITCODE -ne 0) {
  Pop-Location
  throw "npm run check thất bại"
}

New-RunShortcut -DesktopToolDir $desktopToolDir

Write-Host ""
Write-Host "Cài xong!" -ForegroundColor Green
Write-Host "  Thư mục : $desktopToolDir"
Write-Host "  Chạy lại: scripts\run-windows.bat"
Write-Host "  API     : http://127.0.0.1:8795/health"
Write-Host ""
Write-Host "Lần đầu: mở app → Chọn điểm trên màn hình → Test click → bật Tự click sau khi hết giờ." -ForegroundColor Yellow

if (-not $SkipStart) {
  Write-Step "Khởi động desktop-tool"
  npm start
}

Pop-Location
