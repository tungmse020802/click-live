using AutomationDotNet.Models;

namespace AutomationDotNet.Services;

public class ClickSchedulerService
{
    private readonly LoggerService _logger;
    private readonly SettingsService _settingsService;
    private CancellationTokenSource? _clickCts;

    public event Action<long>? OnCountdownStarted;
    public event Action? OnCountdownEnded;
    public event Action<ClickResult>? OnClickCompleted;

    public ClickSchedulerService(LoggerService logger, SettingsService settingsService)
    {
        _logger = logger;
        _settingsService = settingsService;
    }

    public void ScheduleJob(DesktopPullItem item)
    {
        _clickCts?.Cancel();
        _clickCts?.Dispose();
        _clickCts = new CancellationTokenSource();
        var token = _clickCts.Token;

        Task.Run(async () =>
        {
            try
            {
                var settings = _settingsService.Settings;
                double offsetMs = settings.DelayOffsetMs;
                double leadAdvanceMs = OperatingSystem.IsWindows() ? 30.0 : 10.0;

                var schedule = TimingHelper.ResolveSchedule(item, settings, leadAdvanceMs);
                double totalDelayMs = schedule.TotalDelayMs;
                long targetAtMs = schedule.TargetAtMs;
                DateTime targetDisplayTime = TimingHelper.TargetAtMsToLocalDateTime(targetAtMs);

                _logger.Log(
                    "wait",
                    $"Hẹn click sau {totalDelayMs:F0}ms ({schedule.Source})",
                    $"Display={schedule.DisplayRemainingMs:F0}ms, Target={targetDisplayTime:HH:mm:ss.fff}, TargetAtMs={targetAtMs}, Offset={offsetMs:+0.00;-0.00;0.00}ms");
                OnCountdownStarted?.Invoke(targetAtMs);

                long clickAtMs = targetAtMs - (long)Math.Round(leadAdvanceMs);
                while (TimingHelper.NowMs() < clickAtMs)
                {
                    if (token.IsCancellationRequested)
                    {
                        _logger.Log("schedule", "Hủy job click cũ");
                        OnCountdownEnded?.Invoke();
                        return;
                    }

                    long remainingMs = clickAtMs - TimingHelper.NowMs();
                    if (remainingMs > 50)
                        await Task.Delay((int)(remainingMs - 20), token);
                    else if (remainingMs > 5)
                        await Task.Delay(1, token);
                    else
                        Thread.SpinWait(100);
                }

                long clickAtMsActual = TimingHelper.NowMs();
                DateTime actualClickTime = TimingHelper.TargetAtMsToLocalDateTime(clickAtMsActual);

                bool clicked = false;
                if (settings.AutoClickEnabled && (settings.ClickX > 0 || settings.ClickY > 0))
                {
                    _logger.Log("click", $"Thực thi click tại ({settings.ClickX}, {settings.ClickY})");
                    clicked = Win32Native.PerformClick(settings.ClickX, settings.ClickY);
                }
                else
                {
                    _logger.Log("click", "Tắt tự click hoặc chưa chọn tọa độ (X=0, Y=0)");
                }

                double driftMs = clickAtMsActual - targetAtMs;
                string driftStatus = driftMs switch
                {
                    > 30 => $"+{driftMs:F1}ms (trễ)",
                    < -30 => $"{driftMs:F1}ms (sớm)",
                    _ => $"{driftMs:F1}ms (chuẩn)"
                };

                double suggestedOffset = offsetMs - driftMs;
                string hint = $"Gợi ý offset: {suggestedOffset / 1000.0:+0.00;-0.00;0.00}s";

                var result = new ClickResult
                {
                    X = settings.ClickX,
                    Y = settings.ClickY,
                    ClickedAt = actualClickTime,
                    TargetTime = targetDisplayTime,
                    RawTimeLabel = item.TimeLabel,
                    DriftMs = driftMs,
                    OffsetHint = hint,
                    CurrentOffsetMs = offsetMs
                };

                _logger.Log("click", $"Kết quả click: {driftStatus}", hint);
                OnClickCompleted?.Invoke(result);

                // Stop overlay after 2 seconds
                await Task.Delay(2000, token);
                OnCountdownEnded?.Invoke();
            }
            catch (OperationCanceledException)
            {
                OnCountdownEnded?.Invoke();
            }
            catch (Exception ex)
            {
                _logger.Log("error", "Lỗi thực thi job click", ex.Message);
                OnCountdownEnded?.Invoke();
            }
        }, token);
    }
}
