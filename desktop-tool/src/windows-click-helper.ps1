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
  public const uint INPUT_MOUSE = 0;
  public const uint MOUSEEVENTF_MOVE = 0x0001;
  public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
  public const uint MOUSEEVENTF_LEFTUP = 0x0004;
  public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
  public const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

  public const uint WM_MOUSEMOVE = 0x0200;
  public const uint WM_LBUTTONDOWN = 0x0201;
  public const uint WM_LBUTTONUP = 0x0202;
  public const uint WM_LBUTTONDBLCLK = 0x0203;
  public const int MK_LBUTTON = 0x0001;
  public const int SW_SHOW = 5;

  public const int SM_XVIRTUALSCREEN = 76;
  public const int SM_YVIRTUALSCREEN = 77;
  public const int SM_CXVIRTUALSCREEN = 78;
  public const int SM_CYVIRTUALSCREEN = 79;

  [StructLayout(LayoutKind.Sequential)]
  public struct POINT {
    public int X;
    public int Y;
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

  [StructLayout(LayoutKind.Explicit)]
  public struct INPUT {
    [FieldOffset(0)] public uint type;
    [FieldOffset(8)] public MOUSEINPUT mi;
  }

  [DllImport("user32.dll")]
  public static extern bool SetCursorPos(int x, int y);

  [DllImport("user32.dll")]
  public static extern bool GetCursorPos(out POINT lpPoint);

  [DllImport("user32.dll")]
  public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

  [DllImport("user32.dll")]
  static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

  [DllImport("user32.dll")]
  static extern int GetSystemMetrics(int nIndex);

  [DllImport("user32.dll")]
  static extern IntPtr WindowFromPoint(POINT Point);

  [DllImport("user32.dll")]
  static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);

  [DllImport("user32.dll")]
  static extern bool SetForegroundWindow(IntPtr hWnd);

  [DllImport("user32.dll")]
  static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

  [DllImport("user32.dll")]
  static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

  [DllImport("user32.dll")]
  static extern IntPtr ChildWindowFromPoint(IntPtr hWndParent, POINT Point);

  [DllImport("user32.dll")]
  static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

  [DllImport("user32.dll")]
  static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

  [DllImport("user32.dll")]
  static extern IntPtr SetFocus(IntPtr hWnd);

  [DllImport("user32.dll")]
  static extern bool BringWindowToTop(IntPtr hWnd);

  [DllImport("user32.dll")]
  static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

  [DllImport("user32.dll")]
  static extern bool AllowSetForegroundWindow(int dwProcessId);

  [DllImport("kernel32.dll")]
  static extern uint GetCurrentThreadId();

  [DllImport("user32.dll")]
  static extern uint GetDoubleClickTime();

  static string ClickMode() {
    var v = Environment.GetEnvironmentVariable("DESKTOP_CLICK_MODE");
    if (string.IsNullOrEmpty(v)) return "absolute";
    return v.Trim().ToLowerInvariant();
  }

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

  static void ToAbsolute(int x, int y, out int ax, out int ay) {
    int left = GetSystemMetrics(SM_XVIRTUALSCREEN);
    int top = GetSystemMetrics(SM_YVIRTUALSCREEN);
    int w = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    int h = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    int denomX = Math.Max(w - 1, 1);
    int denomY = Math.Max(h - 1, 1);
    ax = (x - left) * 65535 / denomX;
    ay = (y - top) * 65535 / denomY;
  }

  static IntPtr MakeLParam(int x, int y) {
    return (IntPtr)((y << 16) | (x & 0xFFFF));
  }

  static bool SendMouse(uint flags, int dx, int dy) {
    INPUT[] inputs = new INPUT[1];
    inputs[0].type = INPUT_MOUSE;
    inputs[0].mi.dx = dx;
    inputs[0].mi.dy = dy;
    inputs[0].mi.dwFlags = flags;
    return SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT))) == 1;
  }

  static void PressLegacy(bool down) {
    mouse_event(down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
  }

  static bool VerifyCursor(int x, int y, out string detail) {
    detail = "";
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

  static bool MovePointer(int x, int y) {
    if (!SetCursorPos(x, y)) return false;
    int ax, ay;
    ToAbsolute(x, y, out ax, out ay);
    uint moveFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
    return SendMouse(moveFlags, ax, ay);
  }

  static bool ClickAbsolute(int x, int y, out string detail) {
    detail = "mode=absolute";
    if (!MovePointer(x, y)) {
      detail = "mode=absolute,setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    Thread.Sleep(ClickSettleMs());
    if (!SendMouse(MOUSEEVENTF_LEFTDOWN, 0, 0)) {
      detail = "mode=absolute,sendinput-down-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }
    Thread.Sleep(ClickStepMs());
    if (!SendMouse(MOUSEEVENTF_LEFTUP, 0, 0)) {
      detail = "mode=absolute,sendinput-up-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    if (IsDoubleClickEnabled()) {
      Thread.Sleep(DoubleClickGapMs());
      if (!SendMouse(MOUSEEVENTF_LEFTDOWN, 0, 0)) {
        detail = "mode=absolute,sendinput-down2-failed";
        return false;
      }
      Thread.Sleep(ClickStepMs());
      if (!SendMouse(MOUSEEVENTF_LEFTUP, 0, 0)) {
        detail = "mode=absolute,sendinput-up2-failed";
        return false;
      }
    }

    string cursorDetail;
    if (!VerifyCursor(x, y, out cursorDetail)) {
      detail = "mode=absolute," + cursorDetail;
      return false;
    }
    return true;
  }

  static IntPtr ResolveDeepHwnd(int x, int y) {
    POINT screen = new POINT { X = x, Y = y };
    IntPtr hwnd = WindowFromPoint(screen);
    if (hwnd == IntPtr.Zero) return IntPtr.Zero;

    for (int i = 0; i < 20; i++) {
      POINT client = new POINT { X = x, Y = y };
      if (!ScreenToClient(hwnd, ref client)) break;
      IntPtr child = ChildWindowFromPoint(hwnd, client);
      if (child == IntPtr.Zero || child == hwnd) break;
      hwnd = child;
    }
    return hwnd;
  }

  static bool FocusTargetWindow(IntPtr hwnd) {
    if (hwnd == IntPtr.Zero) return false;

    uint pid;
    GetWindowThreadProcessId(hwnd, out pid);
    AllowSetForegroundWindow((int)pid);
    ShowWindow(hwnd, SW_SHOW);
    BringWindowToTop(hwnd);
    SetForegroundWindow(hwnd);
    SetFocus(hwnd);
    Thread.Sleep(ClickSettleMs());
    return true;
  }

  static bool SendMouseMessages(IntPtr hwnd, int x, int y, bool useSendMessage, out string detail) {
    detail = "";
    if (hwnd == IntPtr.Zero) {
      detail = "hwnd-zero";
      return false;
    }

    POINT client = new POINT { X = x, Y = y };
    if (!ScreenToClient(hwnd, ref client)) {
      detail = "screentoclient-failed";
      return false;
    }

    IntPtr lParam = MakeLParam(client.X, client.Y);

    if (useSendMessage) {
      SendMessage(hwnd, WM_MOUSEMOVE, IntPtr.Zero, lParam);
      Thread.Sleep(ClickStepMs());
      SendMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
      Thread.Sleep(ClickStepMs());
      SendMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
      if (IsDoubleClickEnabled()) {
        Thread.Sleep(DoubleClickGapMs());
        SendMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
        Thread.Sleep(ClickStepMs());
        SendMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
      }
    } else {
      PostMessage(hwnd, WM_MOUSEMOVE, IntPtr.Zero, lParam);
      Thread.Sleep(ClickStepMs());
      PostMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
      Thread.Sleep(ClickStepMs());
      PostMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
      if (IsDoubleClickEnabled()) {
        Thread.Sleep(DoubleClickGapMs());
        PostMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
        Thread.Sleep(ClickStepMs());
        PostMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
      }
    }

    return true;
  }

  static bool ClickDeep(int x, int y, out string detail) {
    detail = "mode=deep";
    if (!SetCursorPos(x, y)) {
      detail = "mode=deep,setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    IntPtr hwnd = ResolveDeepHwnd(x, y);
    if (hwnd == IntPtr.Zero) {
      detail = "mode=deep,windowfrompoint-failed";
      return false;
    }

    uint targetTid;
    GetWindowThreadProcessId(hwnd, out targetTid);
    uint selfTid = GetCurrentThreadId();
    bool attached = false;

    try {
      if (targetTid != selfTid) {
        attached = AttachThreadInput(selfTid, targetTid, true);
      }

      FocusTargetWindow(hwnd);

      string msgDetail;
      if (!SendMouseMessages(hwnd, x, y, true, out msgDetail)) {
        detail = "mode=deep," + msgDetail + ",hwnd=" + hwnd.ToInt64();
        return false;
      }

      Thread.Sleep(ClickStepMs());
      SendMouse(MOUSEEVENTF_LEFTDOWN, 0, 0);
      Thread.Sleep(ClickStepMs());
      SendMouse(MOUSEEVENTF_LEFTUP, 0, 0);

      if (IsDoubleClickEnabled()) {
        Thread.Sleep(DoubleClickGapMs());
        SendMouse(MOUSEEVENTF_LEFTDOWN, 0, 0);
        Thread.Sleep(ClickStepMs());
        SendMouse(MOUSEEVENTF_LEFTUP, 0, 0);
      }
    } finally {
      if (attached) {
        AttachThreadInput(selfTid, targetTid, false);
      }
    }

    string cursorDetail;
    if (!VerifyCursor(x, y, out cursorDetail)) {
      detail = "mode=deep," + cursorDetail + ",hwnd=" + hwnd.ToInt64();
      return false;
    }

    detail = "mode=deep,hwnd=" + hwnd.ToInt64();
    return true;
  }

  static bool ClickPostMessage(int x, int y, out string detail) {
    detail = "mode=postmessage";
    if (!SetCursorPos(x, y)) {
      detail = "mode=postmessage,setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    POINT pt = new POINT { X = x, Y = y };
    IntPtr hwnd = WindowFromPoint(pt);
    if (hwnd == IntPtr.Zero) {
      detail = "mode=postmessage,windowfrompoint-failed";
      return false;
    }

    SetForegroundWindow(hwnd);
    Thread.Sleep(ClickSettleMs());

    POINT client = new POINT { X = x, Y = y };
    if (!ScreenToClient(hwnd, ref client)) {
      detail = "mode=postmessage,screentoclient-failed";
      return false;
    }

    IntPtr lParam = MakeLParam(client.X, client.Y);
    if (!PostMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam)) {
      detail = "mode=postmessage,down-failed";
      return false;
    }
    Thread.Sleep(ClickStepMs());
    if (!PostMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam)) {
      detail = "mode=postmessage,up-failed";
      return false;
    }

    if (IsDoubleClickEnabled()) {
      Thread.Sleep(DoubleClickGapMs());
      if (!PostMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam)) {
        detail = "mode=postmessage,down2-failed";
        return false;
      }
      Thread.Sleep(ClickStepMs());
      if (!PostMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam)) {
        detail = "mode=postmessage,up2-failed";
        return false;
      }
    }

    string cursorDetail;
    if (!VerifyCursor(x, y, out cursorDetail)) {
      detail = "mode=postmessage," + cursorDetail;
      return false;
    }
    return true;
  }

  static bool ClickLegacy(int x, int y, out string detail) {
    detail = "mode=legacy";
    if (!SetCursorPos(x, y)) {
      detail = "mode=legacy,setcursorpos-failed,gle=" + Marshal.GetLastWin32Error();
      return false;
    }

    Thread.Sleep(ClickSettleMs());
    PressLegacy(true);
    Thread.Sleep(ClickStepMs());
    PressLegacy(false);

    if (IsDoubleClickEnabled()) {
      Thread.Sleep(DoubleClickGapMs());
      PressLegacy(true);
      Thread.Sleep(ClickStepMs());
      PressLegacy(false);
    }

    string cursorDetail;
    if (!VerifyCursor(x, y, out cursorDetail)) {
      detail = "mode=legacy," + cursorDetail;
      return false;
    }
    return true;
  }

  public static bool ClickAt(int x, int y, out string detail) {
    detail = "";
    string mode = ClickMode();

    if (mode == "legacy") return ClickLegacy(x, y, out detail);
    if (mode == "postmessage") return ClickPostMessage(x, y, out detail);
    if (mode == "deep") return ClickDeep(x, y, out detail);
    if (mode == "absolute") return ClickAbsolute(x, y, out detail);

    // auto: absolute -> deep -> postmessage -> legacy
    if (ClickAbsolute(x, y, out detail)) return true;
    if (ClickDeep(x, y, out detail)) return true;
    if (ClickPostMessage(x, y, out detail)) return true;
    return ClickLegacy(x, y, out detail);
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
