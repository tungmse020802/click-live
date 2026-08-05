namespace AutomationDotNet.Models;

public class ClickResult
{
    public int X { get; set; }
    public int Y { get; set; }
    public DateTime ClickedAt { get; set; }
    public DateTime? TargetTime { get; set; }
    public string RawTimeLabel { get; set; } = "";
    public double DriftMs { get; set; }
    public string OffsetHint { get; set; } = "";
    public double CurrentOffsetMs { get; set; }
}

public class LogEntry
{
    public DateTime Timestamp { get; set; } = DateTime.Now;
    public string EventType { get; set; } = "info"; // poll, schedule, wait, click, error
    public string Message { get; set; } = "";
    public string Details { get; set; } = "";

    public string FullLogLine => $"[{Timestamp:HH:mm:ss.fff}] [{EventType.ToUpper()}] {Message} {(string.IsNullOrEmpty(Details) ? "" : "— " + Details)}".Trim();
}
