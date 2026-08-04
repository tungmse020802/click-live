param(
  [switch]$Once,
  [int]$X = -1,
  [int]$Y = -1
)

$ErrorActionPreference = "Stop"

try {
  Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Threading;
public class ClickLiveDpi {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
  [ClickLiveDpi]::SetProcessDPIAware() | Out-Null
} catch {
}

Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Threading;

public class ClickLiveMouse {
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT {
    public int X;
    public int Y;
  }

  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int x, int y);

  [DllImport("user32.dll")]
  public static extern bool GetCursorPos(out POINT lpPoint);

  [DllImport("user32.dll")]
  public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

  [DllImport("user32.dll")]
  static extern uint GetDoubleClickTime();

  static bool IsDoubleClickEnabled() {
    var v = Environment.GetEnvironmentVariable("DESKTOP_CLICK_DOUBLE");
    if (string.IsNullOrEmpty(v)) return true;
    v = v.Trim().ToLowerInvariant();
    return v != "0" && v != "false" && v != "no";
  }

  static int ClickSettleMs() {
    var v = Environment.GetEnvironmentVariable("DESKTOP_CLICK_SETTLE_MS");
    int n;
    if (int.TryParse(v, out n) && n >= 0) return n;
    return 20;
  }

  static int ClickStepMs() {
    var v = Environment.GetEnvironmentVariable("DESKTOP_CLICK_STEP_MS");
    int n;
    if (int.TryParse(v, out n) && n >= 0) return n;
    return 12;
  }

  static int DoubleClickGapMs() {
    var v = Environment.GetEnvironmentVariable("DESKTOP_CLICK_DOUBLE_GAP_MS");
    int n;
    if (int.TryParse(v, out n) && n >= 0) return n;
    var sys = GetDoubleClickTime();
    if (sys > 0) return Math.Max(40, Math.Min(180, (int)(sys / 3)));
    return 60;
  }

  static void PressButton(bool down) {
    mouse_event(down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
  }

  static void PerformButtonClicks() {
    Thread.Sleep(ClickSettleMs());
    PressButton(true);
    Thread.Sleep(ClickStepMs());
    PressButton(false);
    if (IsDoubleClickEnabled()) {
      Thread.Sleep(DoubleClickGapMs());
      PressButton(true);
      Thread.Sleep(ClickStepMs());
      PressButton(false);
    }
  }

  public static bool ClickAt(int x, int y, out string detail) {
    detail = "";
    if (!SetCursorPos(x, y)) {
      detail = "setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    PerformButtonClicks();

    POINT pt;
    if (!GetCursorPos(out pt)) {
      detail = "getcursorpos-failed";
      return false;
    }
    if (Math.Abs(pt.X - x) > 3 || Math.Abs(pt.Y - y) > 3) {
      detail = "cursor-at:" + pt.X + "," + pt.Y;
      return false;
    }
    return true;
  }
}
"@

if ($Once) {
  if ($X -lt 0 -or $Y -lt 0) {
    Write-Error "Once mode requires -X and -Y"
    exit 2
  }
  $detail = ""
  if ([ClickLiveMouse]::ClickAt($X, $Y, [ref]$detail)) {
    exit 0
  }
  Write-Error $detail
  exit 1
}

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
    $detail = ""
    if ([ClickLiveMouse]::ClickAt($x, $y, [ref]$detail)) {
      [Console]::Out.WriteLine("ok:${id},${x},${y}")
    } else {
      [Console]::Out.WriteLine("err:${id},${detail}")
    }
  } elseif ($line -match '^(-?\d+),(-?\d+)$') {
    [Console]::Out.WriteLine("err:legacy-format")
  } else {
    [Console]::Out.WriteLine("err")
  }
  [Console]::Out.Flush()
}
