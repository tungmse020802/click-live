using System.Runtime.InteropServices;

namespace AutomationDotNet.Services;

public static class Win32Native
{
    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern bool GetCursorPos(out POINT lpPoint);

    [DllImport("user32.dll", SetLastError = true)]
    public static extern void mouse_event(uint dwFlags, uint dx, uint dy, uint dwData, UIntPtr dwExtraInfo);

    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP = 0x0004;

    [StructLayout(LayoutKind.Sequential)]
    public struct POINT
    {
        public int X;
        public int Y;
    }

    /// <summary>
    /// Executes a high-precision Windows native left click at (x, y)
    /// </summary>
    public static bool PerformClick(int x, int y, int clickDurationMs = 20)
    {
        try
        {
            if (OperatingSystem.IsWindows())
            {
                SetCursorPos(x, y);
                mouse_event(MOUSEEVENTF_LEFTDOWN, (uint)x, (uint)y, 0, UIntPtr.Zero);
                if (clickDurationMs > 0)
                {
                    Thread.Sleep(clickDurationMs);
                }
                mouse_event(MOUSEEVENTF_LEFTUP, (uint)x, (uint)y, 0, UIntPtr.Zero);
                return true;
            }
            return false;
        }
        catch
        {
            return false;
        }
    }
}
