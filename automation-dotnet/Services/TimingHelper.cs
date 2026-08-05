using System.Text.RegularExpressions;
using AutomationDotNet.Models;

namespace AutomationDotNet.Services;

public readonly record struct ClickSchedule(
    double TotalDelayMs,
    long TargetAtMs,
    double DisplayRemainingMs,
    string Source);

public static class TimingHelper
{
    private const double MaxStaleMs = 3000;

    public static long NowMs() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

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

    public static DateTime TargetAtMsToLocalDateTime(long targetAtMs) =>
        DateTimeOffset.FromUnixTimeMilliseconds(targetAtMs).LocalDateTime;

    public static ClickSchedule ResolveSchedule(DesktopPullItem item, AppSettings settings, double leadAdvanceMs)
    {
        double offsetMs = settings.DelayOffsetMs;
        long nowMs = NowMs();

        double? absoluteEndMs = ParseAbsoluteTargetMs(item.TimeLabel, nowMs);
        if (absoluteEndMs is > 0 && !IsScheduleTooStale(absoluteEndMs.Value, offsetMs, nowMs))
            return BuildEndTimeSchedule(absoluteEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "message_clock");

        double? serverEndMs = item.EndTimeMs is > 0 ? NormalizeEndTimeMs(item.EndTimeMs.Value) : null;
        if (absoluteEndMs is > 0 && serverEndMs is > 0)
        {
            if (!IsScheduleTooStale(serverEndMs.Value, offsetMs, nowMs))
                return BuildEndTimeSchedule(serverEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "junb_end_time_after_stale_clock");
        }

        if (absoluteEndMs is > 0)
            return BuildEndTimeSchedule(absoluteEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "message_clock_stale");

        if (serverEndMs is > 0)
            return BuildEndTimeSchedule(serverEndMs.Value, offsetMs, leadAdvanceMs, nowMs, "server_end_time");

        if (item.QueuedAtMs is > 0 && item.ClickAfterMs > 0)
        {
            double endMs = NormalizeEndTimeMs(item.QueuedAtMs.Value + item.ClickAfterMs);
            return BuildEndTimeSchedule(endMs, offsetMs, leadAdvanceMs, nowMs, "queued_click_after");
        }

        double rawDelayMs = ResolveRawDelayMs(item);
        if (rawDelayMs <= 0)
            rawDelayMs = Math.Max(0, settings.DefaultWaitSec * 1000);

        long targetAtMs = nowMs + (long)Math.Round(rawDelayMs + offsetMs);
        double displayRemainingMs = targetAtMs - nowMs;
        double totalDelayMs = Math.Max(0, displayRemainingMs - leadAdvanceMs);
        return new ClickSchedule(totalDelayMs, targetAtMs, displayRemainingMs, "click_after");
    }

    private static ClickSchedule BuildEndTimeSchedule(
        double endTimeMs,
        double offsetMs,
        double leadAdvanceMs,
        long nowMs,
        string source)
    {
        long targetAtMs = (long)Math.Round(endTimeMs + offsetMs);
        double displayRemainingMs = targetAtMs - nowMs;
        double totalDelayMs = Math.Max(0, displayRemainingMs - leadAdvanceMs);
        return new ClickSchedule(totalDelayMs, targetAtMs, displayRemainingMs, source);
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
