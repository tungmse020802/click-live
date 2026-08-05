using System.Runtime.InteropServices;

namespace AutomationDotNet.Services;

public static class Win32Native
{
    [DllImport("user32.dll")]
    public static extern bool SetProcessDPIAware();

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);

    public const uint MOUSEEVENTF_MOVE = 0x0001;
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;
    public const uint MOUSEEVENTF_ABSOLUTE = 0x8000;

    public const int SM_CXSCREEN = 0;
    public const int SM_CYSCREEN = 1;

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct INPUT
    {
        public uint type;
        public MOUSEINPUT mi;
    }

    [StructLayout(LayoutKind.Sequential)]
    public struct MOUSEINPUT
    {
        public int dx;
        public int dy;
        public uint mouseData;
        public uint dwFlags;
        public uint time;
        public UIntPtr dwExtraInfo;
    }

    public const uint INPUT_MOUSE = 0;

    static Win32Native()
    {
        try
        {
            if (OperatingSystem.IsWindows())
            {
                SetProcessDPIAware();
            }
        }
        catch { }
    }

    /// <summary>
    /// Forces an atomic, un-interruptible native Windows left click at (x, y)
    /// </summary>
    public static bool PerformClick(int x, int y, bool doubleClick = true)
    {
        try
        {
            if (!OperatingSystem.IsWindows()) return false;

            int screenWidth = GetSystemMetrics(SM_CXSCREEN);
            int screenHeight = GetSystemMetrics(SM_CYSCREEN);
            if (screenWidth <= 0) screenWidth = 1920;
            if (screenHeight <= 0) screenHeight = 1080;

            // Absolute normalized coordinates (0 to 65535) for Windows hardware mouse driver
            int absX = (int)Math.Round(x * 65535.0 / (screenWidth - 1));
            int absY = (int)Math.Round(y * 65535.0 / (screenHeight - 1));

            // 1. Force cursor position at OS level
            SetCursorPos(x, y);

            // 2. Prepare Atomic SendInput sequence (Move -> Down -> Up)
            INPUT[] inputs = new INPUT[doubleClick ? 6 : 3];

            // Single click sequence
            inputs[0] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE);
            inputs[1] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN);
            inputs[2] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP);

            if (doubleClick)
            {
                // Rapid second click (double click)
                inputs[3] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE);
                inputs[4] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTDOWN);
                inputs[5] = CreateMouseInput(absX, absY, MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_LEFTUP);
            }

            uint result = SendInput((uint)inputs.Length, inputs, Marshal.SizeOf(typeof(INPUT)));

            // 3. Fallback mouse_event if SendInput is blocked by UIPI
            if (result == 0)
            {
                SetCursorPos(x, y);
                mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN, (uint)absX, (uint)absY, 0, UIntPtr.Zero);
                Thread.Sleep(15);
                SetCursorPos(x, y);
                mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP, (uint)absX, (uint)absY, 0, UIntPtr.Zero);

                if (doubleClick)
                {
                    Thread.Sleep(40);
                    SetCursorPos(x, y);
                    mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTDOWN, (uint)absX, (uint)absY, 0, UIntPtr.Zero);
                    Thread.Sleep(15);
                    SetCursorPos(x, y);
                    mouse_event(MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_MOVE | MOUSEEVENTF_LEFTUP, (uint)absX, (uint)absY, 0, UIntPtr.Zero);
                }
            }

            // 4. Re-enforce final position
            SetCursorPos(x, y);
            return true;
        }
        catch
        {
            return false;
        }
    }

    private static INPUT CreateMouseInput(int absX, int absY, uint flags)
    {
        return new INPUT
        {
            type = INPUT_MOUSE,
            mi = new MOUSEINPUT
            {
                dx = absX,
                dy = absY,
                mouseData = 0,
                dwFlags = flags,
                time = 0,
                dwExtraInfo = UIntPtr.Zero
            }
        };
    }
}
