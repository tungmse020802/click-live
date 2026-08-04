$ErrorActionPreference = "Stop"

try {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ClickLiveDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
  [ClickLiveDpi]::SetProcessDPIAware() | Out-Null
} catch {
  # DPI API không có trên một số bản Windows — bỏ qua
}

$sig = @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);
'@

$null = Add-Type -MemberDefinition $sig -Name WinMouse -Namespace ClickLive -PassThru

[Console]::Out.WriteLine("ready")
[Console]::Out.Flush()

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $line = $line.Trim()
  if ($line -eq "quit") { break }
  if ($line -match '^(\d+),(-?\d+),(-?\d+)$') {
    $id = [int]$Matches[1]
    $x = [int]$Matches[2]
    $y = [int]$Matches[3]
    [ClickLive.WinMouse]::SetCursorPos($x, $y) | Out-Null
    [ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)
    [ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)
    [Console]::Out.WriteLine("ok:${id},${x},${y}")
  } elseif ($line -match '^(-?\d+),(-?\d+)$') {
    # legacy: id=0
    $x = [int]$Matches[1]
    $y = [int]$Matches[2]
    [ClickLive.WinMouse]::SetCursorPos($x, $y) | Out-Null
    [ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)
    [ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)
    [Console]::Out.WriteLine("ok:0,${x},${y}")
  } else {
    [Console]::Out.WriteLine("err")
  }
  [Console]::Out.Flush()
}
