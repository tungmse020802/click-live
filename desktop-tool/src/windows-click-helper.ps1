param(
  [switch]$Once,
  [int]$X = -1,
  [int]$Y = -1
)

$ErrorActionPreference = "Stop"

# Giữ system-DPI-aware — khớp tọa độ screenX/screenY từ Electron (tránh lệch PerMonitorV2).
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

Add-Type @"
using System;
using System.Runtime.InteropServices;

public class ClickLiveMouse {
  public const uint INPUT_MOUSE = 0;
  public const uint MOUSEEVENTF_MOVE = 0x0001;
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
  public const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

  [StructLayout(LayoutKind.Sequential)]
  public struct INPUT {
    public uint type;
    public MOUSEINPUT mi;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct MOUSEINPUT {
    public int dx;
    public int dy;
    public uint mouseData;
    public uint dwFlags;
    public uint time;
    public IntPtr dwExtraInfo;
  }

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT {
    public int X;
    public int Y;
  }

  [DllImport("user32.dll", SetLastError = true)]
  public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int x, int y);

  [DllImport("user32.dll")]
  public static extern bool GetCursorPos(out POINT lpPoint);

  public static bool ClickAt(int x, int y, out string detail) {
    detail = "";
    if (!SetCursorPos(x, y)) {
      detail = "setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    var inputSize = Marshal.SizeOf(typeof(INPUT));
    var inputs = new INPUT[2];

    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dwFlags = MOUSEEVENTF_LEFTDOWN;

    inputs[1].type = INPUT_MOUSE;
    inputs[1].mi.dwFlags = MOUSEEVENTF_LEFTUP;

    var sent = SendInput(2, inputs, inputSize);
    if (sent != 2) {
      detail = "sendinput:" + sent + ",gle=" + Marshal.GetLastWin32Error();
      return false;
    }

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
