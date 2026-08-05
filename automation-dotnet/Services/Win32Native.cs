using System.Runtime.InteropServices;

namespace AutomationDotNet.Services;

public readonly record struct ClickPerformResult(bool Ok, string Method, string Detail);

public static class Win32Native
{
    private const int CursorTolerancePx = 3;
    private const int ClickSettleMs = 20;
    private const int ClickStepMs = 12;
    private const int DoubleClickGapMs = 60;

    private const uint MOUSEEVENTF_MOVE = 0x0001;
    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP = 0x0004;
    private const uint MOUSEEVENTF_ABSOLUTE = 0x8000;
    private const uint MOUSEEVENTF_VIRTUALDESK = 0x4000;

    private const uint WM_MOUSEMOVE = 0x0200;
    private const uint WM_LBUTTONDOWN = 0x0201;
    private const uint WM_LBUTTONUP = 0x0202;
    private const int MK_LBUTTON = 0x0001;
    private const int SW_SHOW = 5;

    private const int SM_XVIRTUALSCREEN = 76;
    private const int SM_YVIRTUALSCREEN = 77;
    private const int SM_CXVIRTUALSCREEN = 78;
    private const int SM_CYVIRTUALSCREEN = 79;

    public const uint INPUT_MOUSE = 0;

    [DllImport("user32.dll")]
    private static extern bool SetProcessDPIAware();

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool SetCursorPos(int x, int y);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    private static extern int GetSystemMetrics(int nIndex);

    [DllImport("user32.dll")]
    private static extern uint GetDoubleClickTime();

    [DllImport("user32.dll")]
    private static extern IntPtr WindowFromPoint(POINT point);

    [DllImport("user32.dll")]
    private static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);

    [DllImport("user32.dll")]
    private static extern IntPtr ChildWindowFromPoint(IntPtr hWndParent, POINT point);

    [DllImport("user32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    private static extern IntPtr SetFocus(IntPtr hWnd);

    [DllImport("user32.dll")]
    private static extern bool AllowSetForegroundWindow(int dwProcessId);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);

    [DllImport("user32.dll")]
    private static extern bool AttachThreadInput(uint idAttach, uint idAttachTo, bool fAttach);

    [DllImport("user32.dll")]
    private static extern IntPtr SendMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    private static extern bool PostMessage(IntPtr hWnd, uint msg, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll")]
    private static extern uint GetCurrentThreadId();

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    [StructLayout(LayoutKind.Explicit)]
    private struct INPUT
    {
        [FieldOffset(0)] public uint type;
        [FieldOffset(8)] public MOUSEINPUT mi;
    }

    private static readonly int InputSize = Marshal.SizeOf<INPUT>();

    static Win32Native()
    {
        try
        {
            if (OperatingSystem.IsWindows())
                SetProcessDPIAware();
        }
        catch { }
    }

    public static bool PerformClick(int x, int y, bool doubleClick = true) =>
        PerformClickDetailed(x, y, doubleClick).Ok;

    public static ClickPerformResult PerformClickDetailed(int x, int y, bool doubleClick = true)
    {
        if (!OperatingSystem.IsWindows())
            return new ClickPerformResult(false, "none", "not-windows");

        if (ClickAbsolute(x, y, doubleClick, out string absoluteDetail))
            return new ClickPerformResult(true, "absolute", absoluteDetail);

        if (ClickDeep(x, y, doubleClick, out string deepDetail))
            return new ClickPerformResult(true, "deep", deepDetail);

        if (ClickPostMessage(x, y, doubleClick, out string postDetail))
            return new ClickPerformResult(true, "postmessage", postDetail);

        if (ClickLegacy(x, y, doubleClick, out string legacyDetail))
            return new ClickPerformResult(true, "legacy", legacyDetail);

        return new ClickPerformResult(false, "none", legacyDetail);
    }

    private static bool ClickLegacy(int x, int y, bool doubleClick, out string detail)
    {
        detail = "mode=legacy";
        if (!SetCursorPos(x, y))
        {
            detail = "mode=legacy,setcursorpos-failed";
            return false;
        }

        SleepMs(ClickSettleMs);
        PressLegacy(true);
        SleepMs(ClickStepMs);
        PressLegacy(false);

        if (doubleClick)
        {
            SleepMs(DoubleClickGapMs);
            PressLegacy(true);
            SleepMs(ClickStepMs);
            PressLegacy(false);
        }

        if (!VerifyCursor(x, y, out string cursorDetail))
        {
            detail = $"mode=legacy,{cursorDetail}";
            return false;
        }

        return true;
    }

    private static bool ClickAbsolute(int x, int y, bool doubleClick, out string detail)
    {
        detail = "mode=absolute";
        if (!MovePointer(x, y))
        {
            detail = "mode=absolute,move-failed";
            return false;
        }

        IntPtr hwnd = ResolveDeepHwnd(x, y);
        if (hwnd != IntPtr.Zero)
            FocusTargetWindow(hwnd);
        else
            SleepMs(ClickSettleMs);

        if (!SendMouseButton(true))
        {
            detail = "mode=absolute,down-failed";
            return false;
        }

        SleepMs(ClickStepMs);
        if (!SendMouseButton(false))
        {
            detail = "mode=absolute,up-failed";
            return false;
        }

        if (doubleClick)
        {
            SleepMs(DoubleClickGapMs);
            if (!SendMouseButton(true) || !SleepAndSendUp())
            {
                detail = "mode=absolute,double-failed";
                return false;
            }
        }

        if (!VerifyCursor(x, y, out string cursorDetail))
        {
            detail = $"mode=absolute,{cursorDetail}";
            return false;
        }

        return true;
    }

    private static bool SleepAndSendUp()
    {
        SleepMs(ClickStepMs);
        return SendMouseButton(false);
    }

    private static bool ClickDeep(int x, int y, bool doubleClick, out string detail)
    {
        detail = "mode=deep";
        if (!SetCursorPos(x, y))
        {
            detail = "mode=deep,setcursorpos-failed";
            return false;
        }

        IntPtr hwnd = ResolveDeepHwnd(x, y);
        if (hwnd == IntPtr.Zero)
        {
            detail = "mode=deep,windowfrompoint-failed";
            return false;
        }

        uint targetTid = GetWindowThreadProcessId(hwnd, out _);
        uint selfTid = GetCurrentThreadId();
        bool attached = false;

        try
        {
            if (targetTid != selfTid)
                attached = AttachThreadInput(selfTid, targetTid, true);

            FocusTargetWindow(hwnd);

            if (!SendMouseMessages(hwnd, x, y, useSendMessage: true, doubleClick))
            {
                detail = $"mode=deep,sendmessage-failed,hwnd={hwnd}";
                return false;
            }

            SleepMs(ClickStepMs);
            SendMouseButton(true);
            SleepMs(ClickStepMs);
            SendMouseButton(false);

            if (doubleClick)
            {
                SleepMs(DoubleClickGapMs);
                SendMouseButton(true);
                SleepMs(ClickStepMs);
                SendMouseButton(false);
            }
        }
        finally
        {
            if (attached)
                AttachThreadInput(selfTid, targetTid, false);
        }

        if (!VerifyCursor(x, y, out string cursorDetail))
        {
            detail = $"mode=deep,{cursorDetail},hwnd={hwnd}";
            return false;
        }

        detail = $"mode=deep,hwnd={hwnd}";
        return true;
    }

    private static bool ClickPostMessage(int x, int y, bool doubleClick, out string detail)
    {
        detail = "mode=postmessage";
        if (!SetCursorPos(x, y))
        {
            detail = "mode=postmessage,setcursorpos-failed";
            return false;
        }

        POINT pt = new() { X = x, Y = y };
        IntPtr hwnd = WindowFromPoint(pt);
        if (hwnd == IntPtr.Zero)
        {
            detail = "mode=postmessage,windowfrompoint-failed";
            return false;
        }

        SetForegroundWindow(hwnd);
        SleepMs(ClickSettleMs);

        if (!SendMouseMessages(hwnd, x, y, useSendMessage: false, doubleClick))
        {
            detail = "mode=postmessage,messages-failed";
            return false;
        }

        if (!VerifyCursor(x, y, out string cursorDetail))
        {
            detail = $"mode=postmessage,{cursorDetail}";
            return false;
        }

        return true;
    }

    private static bool MovePointer(int x, int y)
    {
        if (!SetCursorPos(x, y))
            return false;

        ToAbsolute(x, y, out int absX, out int absY);
        uint moveFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK;
        return SendMouse(moveFlags, absX, absY);
    }

    private static void ToAbsolute(int x, int y, out int absX, out int absY)
    {
        int left = GetSystemMetrics(SM_XVIRTUALSCREEN);
        int top = GetSystemMetrics(SM_YVIRTUALSCREEN);
        int width = GetSystemMetrics(SM_CXVIRTUALSCREEN);
        int height = GetSystemMetrics(SM_CYVIRTUALSCREEN);
        int denomX = Math.Max(width - 1, 1);
        int denomY = Math.Max(height - 1, 1);
        absX = (x - left) * 65535 / denomX;
        absY = (y - top) * 65535 / denomY;
    }

    private static bool SendMouse(uint flags, int dx, int dy)
    {
        INPUT[] inputs =
        [
            new INPUT
            {
                type = INPUT_MOUSE,
                mi = new MOUSEINPUT
                {
                    dx = dx,
                    dy = dy,
                    dwFlags = flags,
                    mouseData = 0,
                    time = 0,
                    dwExtraInfo = UIntPtr.Zero
                }
            }
        ];
        return SendInput(1, inputs, InputSize) == 1;
    }

    private static bool SendMouseButton(bool down) =>
        SendMouse(down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP, 0, 0);

    private static void PressLegacy(bool down) =>
        mouse_event(down ? MOUSEEVENTF_LEFTDOWN : MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);

    private static bool VerifyCursor(int x, int y, out string detail)
    {
        detail = "";
        if (!GetCursorPos(out POINT pt))
        {
            detail = "getcursorpos-failed";
            return false;
        }

        if (Math.Abs(pt.X - x) > CursorTolerancePx || Math.Abs(pt.Y - y) > CursorTolerancePx)
        {
            detail = $"cursor-at:{pt.X},{pt.Y}";
            return false;
        }

        return true;
    }

    private static IntPtr ResolveDeepHwnd(int x, int y)
    {
        POINT screen = new() { X = x, Y = y };
        IntPtr hwnd = WindowFromPoint(screen);
        if (hwnd == IntPtr.Zero)
            return IntPtr.Zero;

        for (int i = 0; i < 20; i++)
        {
            POINT client = new() { X = x, Y = y };
            if (!ScreenToClient(hwnd, ref client))
                break;

            IntPtr child = ChildWindowFromPoint(hwnd, client);
            if (child == IntPtr.Zero || child == hwnd)
                break;

            hwnd = child;
        }

        return hwnd;
    }

    private static void FocusTargetWindow(IntPtr hwnd)
    {
        if (hwnd == IntPtr.Zero)
            return;

        GetWindowThreadProcessId(hwnd, out uint pid);
        AllowSetForegroundWindow((int)pid);
        ShowWindow(hwnd, SW_SHOW);
        BringWindowToTop(hwnd);
        SetForegroundWindow(hwnd);
        SetFocus(hwnd);
        SleepMs(ClickSettleMs);
    }

    private static bool SendMouseMessages(IntPtr hwnd, int x, int y, bool useSendMessage, bool doubleClick = true)
    {
        POINT client = new() { X = x, Y = y };
        if (!ScreenToClient(hwnd, ref client))
            return false;

        IntPtr lParam = MakeLParam(client.X, client.Y);
        SendMouseMessagePair(hwnd, lParam, useSendMessage);

        if (doubleClick)
        {
            SleepMs(DoubleClickGapMs);
            SendMouseMessagePair(hwnd, lParam, useSendMessage);
        }

        return true;
    }

    private static void SendMouseMessagePair(IntPtr hwnd, IntPtr lParam, bool useSendMessage)
    {
        if (useSendMessage)
        {
            SendMessage(hwnd, WM_MOUSEMOVE, IntPtr.Zero, lParam);
            SleepMs(ClickStepMs);
            SendMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
            SleepMs(ClickStepMs);
            SendMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
        }
        else
        {
            PostMessage(hwnd, WM_MOUSEMOVE, IntPtr.Zero, lParam);
            SleepMs(ClickStepMs);
            PostMessage(hwnd, WM_LBUTTONDOWN, (IntPtr)MK_LBUTTON, lParam);
            SleepMs(ClickStepMs);
            PostMessage(hwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
        }
    }

    private static IntPtr MakeLParam(int x, int y) =>
        (IntPtr)((y << 16) | (x & 0xFFFF));

    private static void SleepMs(int ms)
    {
        if (ms <= 0)
            return;

        long end = Environment.TickCount64 + ms;
        while (Environment.TickCount64 < end)
            Thread.SpinWait(50);
    }
}
