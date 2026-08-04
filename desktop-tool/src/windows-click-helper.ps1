$ErrorActionPreference = "Stop"

try {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ClickLiveDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr value);
  public static readonly IntPtr PerMonitorV2 = (IntPtr)(-4);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
  if (-not [ClickLiveDpi]::SetProcessDpiAwarenessContext([ClickLiveDpi]::PerMonitorV2)) {
    [ClickLiveDpi]::SetProcessDPIAware() | Out-Null
  }
} catch {
  # DPI API không có trên một số bản Windows — bỏ qua
}

$sig = @'
[DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);
[DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint cButtons, uint dwExtraInfo);
'@

$null = Add-Type -MemberDefinition $sig -Name WinMouse -Namespace ClickLive -PassThru

$clickRx = [regex]'^(\d+),(-?\d+),(-?\d+)$'
$pingRx = [regex]'^ping:(\d+)$'

[Console]::Out.WriteLine("ready")
[Console]::Out.Flush()

while ($true) {
  $line = [Console]::In.ReadLine()
  if ($null -eq $line) { break }
  $line = $line.Trim()
  if ($line -eq "quit") { break }

  if ($line -eq "ping") {
    [Console]::Out.WriteLine("pong")
    [Console]::Out.Flush()
    continue
  }

  $pingMatch = $pingRx.Match($line)
  if ($pingMatch.Success) {
    $id = $pingMatch.Groups[1].Value
    [Console]::Out.WriteLine("pong:$id")
    [Console]::Out.Flush()
    continue
  }

  $clickMatch = $clickRx.Match($line)
  if ($clickMatch.Success) {
    $id = [int]$clickMatch.Groups[1].Value
    $x = [int]$clickMatch.Groups[2].Value
    $y = [int]$clickMatch.Groups[3].Value
    [ClickLive.WinMouse]::SetCursorPos($x, $y) | Out-Null
    [ClickLive.WinMouse]::mouse_event(0x0002, 0, 0, 0, 0)
    [ClickLive.WinMouse]::mouse_event(0x0004, 0, 0, 0, 0)
    [Console]::Out.WriteLine("ok:${id},${x},${y}")
  } elseif ($line -match '^(-?\d+),(-?\d+)$') {
    [Console]::Out.WriteLine("err:legacy-format")
  } else {
    [Console]::Out.WriteLine("err")
  }
  [Console]::Out.Flush()
}
