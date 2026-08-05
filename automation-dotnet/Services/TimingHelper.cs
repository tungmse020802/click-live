using System.Text.RegularExpressions;
using AutomationDotNet.Models;

namespace AutomationDotNet.Services;

public readonly record struct ClickSchedule(
    double TotalDelayMs,
    DateTime TargetDisplayTime,
    double DisplayRemainingMs,
    string Source);

public static class TimingHelper
{
    private const double MaxStaleMs = 3000;

    public static double ParseTimeDelayMs(string? label)
    {
        if (string.IsNullOrWhiteSpace(label))
            return 0;

        var match = Regex.Match(label, @"(\d{1,2}):(\d{2})\s*s?", RegexOptions.IgnoreCase);
        if (match.Success)
        {
            int minutes = int.Parse(match.Groups[1].Value);
            int seconds = int.Parse(match.Groups[2].Value);
            return (minutes * 60 + seconds) * 1000;
        }

        match = Regex.Match(label, @"(\d+(?:\.\d+)?)\s*s", RegexOptions.IgnoreCase);
        if (match.Success && double.TryParse(match.Groups[1].Value, out double sec))
            return sec * 1000;

        return 0;
    }

    public static double ResolveRawDelayMs(DesktopPullItem item)
    {
        if (item.ClickAfterMs > 0)
            return item.ClickAfterMs;

        return ParseTimeDelayMs(item.TimeLabel);
    }

    public static string FormatRemainingSeconds(double remainingSec)
    {
        if (remainingSec >= 60)
        {
            int mins = (int)(remainingSec / 60);
            double secs = remainingSec - mins * 60;
            return $"{mins:D2}:{secs:00.00}";
        }

        return remainingSec.ToString("F2");
    }

    public static ClickSchedule ResolveSchedule(DesktopPullItem item, AppSettings settings, double leadAdvanceMs)
    {
        double offsetMs = settings.DelayOffsetMs;
        long nowMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        double? absoluteEndMs = ParseAbsoluteTargetMs(item.TimeLabel, nowMs);
        if (absoluteEndMs is > 0 && !IsScheduleTooStale(absoluteEndMs.Value, offsetMs, nowMs))
            return BuildEndTimeSchedule(absoluteEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "message_clock");

        double? endMs = null;
        string source = "";
        if (item.EndTimeMs is > 0)
        {
            endMs = NormalizeEndTimeMs(item.EndTimeMs.Value);
            source = absoluteEndMs is > 0 ? "junb_end_time_after_stale_clock" : "server_end_time";
        }

        if (absoluteEndMs is > 0 && endMs is null)
            return BuildEndTimeSchedule(absoluteEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "message_clock_stale");

        if (endMs is null && item.QueuedAtMs is > 0 && item.ClickAfterMs > 0)
        {
            endMs = NormalizeEndTimeMs(item.QueuedAtMs.Value + item.ClickAfterMs);
            source = "queued_click_after";
        }

        if (endMs is > 0)
            return BuildEndTimeSchedule(endMs.Value, offsetMs, leadAdvanceMs, nowMs, source);

        double rawDelayMs = ResolveRawDelayMs(item);
        if (rawDelayMs <= 0)
            rawDelayMs = Math.Max(0, settings.DefaultWaitSec * 1000);

        double displayRemainingMs = rawDelayMs + offsetMs;
        double totalDelayMs = Math.Max(0, displayRemainingMs - leadAdvanceMs);
        var targetDisplayTime = DateTime.Now.AddMilliseconds(displayRemainingMs);
        return new ClickSchedule(totalDelayMs, targetDisplayTime, displayRemainingMs, "click_after");
    }

    private static ClickSchedule BuildEndTimeSchedule(
        double endTimeMs,
        double offsetMs,
        double leadAdvanceMs,
        long nowMs,
        string source)
    {
        double displayRemainingMs = endTimeMs - nowMs + offsetMs;
        double targetEpochMs = endTimeMs + offsetMs;
        var targetDisplay = DateTimeOffset.FromUnixTimeMilliseconds((long)Math.Round(targetEpochMs)).LocalDateTime;
        double totalDelayMs = Math.Max(0, endTimeMs - nowMs + offsetMs - leadAdvanceMs);
        return new ClickSchedule(totalDelayMs, targetDisplay, displayRemainingMs, source);
    }

    private static double NormalizeEndTimeMs(double raw)
    {
        if (raw <= 0)
            return 0;
        return raw < 1_000_000_000_000 ? raw * 1000 : raw;
    }

    private static bool IsScheduleTooStale(double endTimeMs, double offsetMs, long nowMs)
    {
        double displayTarget = endTimeMs + offsetMs;
        return nowMs - displayTarget > MaxStaleMs;
    }

    // Mốc HH:MM:SS trong TIME tin nhắn (vd. 01:19s - 23:11:16).
    private static double? ParseAbsoluteTargetMs(string? timeLabel, long nowMs)
    {
        if (string.IsNullOrWhiteSpace(timeLabel))
            return null;

        var match = Regex.Match(
            timeLabel,
            @"(?:-\s*|TIME\s*[:：]\s*)(\d{1,2}):(\d{2}):(\d{2})\b",
            RegexOptions.IgnoreCase);
        if (!match.Success)
        {
            match = Regex.Match(timeLabel, @"\b(\d{1,2}):(\d{2}):(\d{2})\s*$");
            if (!match.Success)
                return null;
        }

        if (!int.TryParse(match.Groups[1].Value, out int rawH)
            || !int.TryParse(match.Groups[2].Value, out int mm)
            || !int.TryParse(match.Groups[3].Value, out int ss))
            return null;

        int hh = rawH % 24;
        var nowLocal = DateTimeOffset.FromUnixTimeMilliseconds(nowMs).LocalDateTime;
        var target = new DateTime(nowLocal.Year, nowLocal.Month, nowLocal.Day, hh, mm, ss, DateTimeKind.Local);
        if (target < nowLocal.AddHours(-12))
            target = target.AddDays(1);

        return new DateTimeOffset(target).ToUnixTimeMilliseconds();
    }
}
