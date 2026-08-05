using System.Diagnostics;
using System.IO;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Media;
using AutomationDotNet.Models;
using AutomationDotNet.Services;

namespace AutomationDotNet;

public partial class MainWindow : Window
{
    private readonly SettingsService _settingsService;
    private readonly LoggerService _logger;
    private readonly QueuePollerService _poller;
    private readonly ClickSchedulerService _scheduler;
    private readonly CountdownOverlayWindow _overlayWindow;
    private readonly List<string> _logLines = new();

    public MainWindow()
    {
        _settingsService = new SettingsService();
        _logger = new LoggerService();
        _poller = new QueuePollerService(_logger);
        _scheduler = new ClickSchedulerService(_logger, _settingsService);
        _overlayWindow = new CountdownOverlayWindow();

        InitializeComponent();

        TxtLogPath.Text = _logger.LogDirectory;

        _logger.OnLogEntryAdded += Logger_OnLogEntryAdded;
        _poller.OnAuthStatusChanged += Poller_OnAuthStatusChanged;
        _poller.OnNewJobArrived += Poller_OnNewJobArrived;
        _scheduler.OnClickCompleted += Scheduler_OnClickCompleted;

        _scheduler.OnCountdownStarted += targetTime => Dispatcher.Invoke(() => _overlayWindow.StartCountdown(targetTime));
        _scheduler.OnCountdownEnded += () => Dispatcher.Invoke(() => _overlayWindow.StopCountdown());

        LoadSettingsToUI();

        Loaded += (_, _) =>
        {
            _overlayWindow.Show();
            _ = TryAutoConnectAsync();
        };

        Closing += (_, _) =>
        {
            try { _overlayWindow.Close(); } catch { }
        };
    }

    private async Task TryAutoConnectAsync()
    {
        var url = _settingsService.Settings.QueueUrl?.Trim();
        var user = _settingsService.Settings.QueueUsername?.Trim();
        var pass = _settingsService.Settings.QueuePassword;
        if (string.IsNullOrEmpty(url) || string.IsNullOrEmpty(user) || string.IsNullOrEmpty(pass))
        {
            return;
        }

        try
        {
            BtnLogin.IsEnabled = false;
            TxtStatus.Text = "Đang tự động đăng nhập kết nối queue server...";
            bool ok = await _poller.LoginAsync(url, user, pass);
            if (ok)
            {
                _settingsService.Settings.PullToken = _poller.ActivePullToken;
                _settingsService.SaveSettings();

                _poller.StartPolling(url, _poller.ActivePullToken, user);
                TxtStatus.Text = "Sẵn sàng — đã tự động kết nối queue server.";
            }
        }
        catch (Exception ex)
        {
            TxtStatus.Text = $"Tự động đăng nhập chưa thành công: {ex.Message}";
        }
        finally
        {
            BtnLogin.IsEnabled = true;
        }
    }

    private void Logger_OnLogEntryAdded(LogEntry entry)
    {
        Dispatcher.InvokeAsync(() =>
        {
            _logLines.Add(entry.FullLogLine);
            while (_logLines.Count > 200) _logLines.RemoveAt(0);
            TxtLogArea.Text = string.Join(Environment.NewLine, _logLines);
            TxtLogArea.ScrollToEnd();
        });
    }

    private void LoadSettingsToUI()
    {
        var s = _settingsService.Settings;
        TxtQueueUrl.Text = s.QueueUrl;
        TxtUsername.Text = s.QueueUsername;
        TxtPassword.Password = s.QueuePassword;
        TxtDefaultWaitSec.Text = s.DefaultWaitSec.ToString("F1");
        ChkAutoClick.IsChecked = s.AutoClickEnabled;
        TxtClickX.Text = s.ClickX.ToString();
        TxtClickY.Text = s.ClickY.ToString();
        UpdateDelayLabel();
    }

    private void UpdateDelayLabel()
    {
        if (_settingsService?.Settings == null) return;
        double offsetMs = _settingsService.Settings.DelayOffsetMs;
        double sec = offsetMs / 1000.0;
        TxtDelayLabel.Text = $"{sec:+0.00;-0.00;0.00}s";
        TxtDelayLabel.Foreground = (Brush)FindResource(offsetMs >= 0 ? "GreenBrush" : "RedBrush");

        if (offsetMs == 0)
        {
            TxtOffsetExplain.Text = "Không offset: Click vừa đúng lúc mốc overlay = 0.0s (sớm hơn ~30ms để bù OS).";
        }
        else if (offsetMs > 0)
        {
            TxtOffsetExplain.Text = $"Cộng +{sec:F2}s: Overlay mốc 0.0s sẽ trễ hơn TIME trong tin {sec:F2} giây.";
        }
        else
        {
            TxtOffsetExplain.Text = $"Trừ {sec:F2}s: Overlay mốc 0.0s sẽ sớm hơn TIME trong tin {Math.Abs(sec):F2} giây.";
        }
    }

    private async void BtnLogin_Click(object sender, RoutedEventArgs e)
    {
        var url = TxtQueueUrl.Text.Trim();
        var user = TxtUsername.Text.Trim();
        var pass = TxtPassword.Password;

        try
        {
            BtnLogin.IsEnabled = false;
            TxtStatus.Text = "Đang đăng nhập...";
            bool ok = await _poller.LoginAsync(url, user, pass);
            if (ok)
            {
                _settingsService.Settings.QueueUrl = url;
                _settingsService.Settings.QueueUsername = user;
                _settingsService.Settings.QueuePassword = pass;
                _settingsService.Settings.PullToken = _poller.ActivePullToken;
                _settingsService.SaveSettings();

                _poller.StartPolling(url, _poller.ActivePullToken, user);
                TxtStatus.Text = "Sẵn sàng — đã kết nối queue server.";
            }
        }
        catch (Exception ex)
        {
            TxtStatus.Text = $"Lỗi đăng nhập: {ex.Message}";
        }
        finally
        {
            BtnLogin.IsEnabled = true;
        }
    }

    private void BtnLogout_Click(object sender, RoutedEventArgs e)
    {
        _poller.StopPolling();
        _settingsService.Settings.PullToken = "";
        _settingsService.SaveSettings();
        Poller_OnAuthStatusChanged("");
        TxtStatus.Text = "Đã đăng xuất.";
    }

    private void Poller_OnAuthStatusChanged(string username)
    {
        Dispatcher.Invoke(() =>
        {
            if (!string.IsNullOrEmpty(username))
            {
                LoggedInPanel.Visibility = Visibility.Visible;
                LoginPanel.Visibility = Visibility.Collapsed;
                TxtLoggedInUser.Text = username;
            }
            else
            {
                LoggedInPanel.Visibility = Visibility.Collapsed;
                LoginPanel.Visibility = Visibility.Visible;
            }
        });
    }

    private void Poller_OnNewJobArrived(DesktopPullItem item)
    {
        Dispatcher.Invoke(() =>
        {
            TxtStatus.Text = $"Nhận job mới: {item.TimeLabel} — ClickAfter={item.ClickAfterMs}ms";
            _scheduler.ScheduleJob(item);
        });
    }

    private void Scheduler_OnClickCompleted(ClickResult result)
    {
        Dispatcher.Invoke(() =>
        {
            ClickResultCard.Visibility = Visibility.Visible;
            TxtResultPos.Text = $"({result.X}, {result.Y})";
            TxtResultClickedAt.Text = result.ClickedAt.ToString("HH:mm:ss.fff");
            TxtResultTarget.Text = result.TargetTime?.ToString("HH:mm:ss.fff") ?? "—";
            TxtResultDrift.Text = $"{result.DriftMs:+0.0;-0.0;0.0}ms";
            TxtResultDrift.Foreground = (Brush)FindResource(Math.Abs(result.DriftMs) <= 30 ? "GreenBrush" : "RedBrush");
            TxtResultHint.Text = result.OffsetHint;
            TxtResultOffset.Text = $"{result.CurrentOffsetMs / 1000.0:+0.00;-0.00;0.00}s";
            TxtStatus.Text = $"Click hoàn tất lúc {result.ClickedAt:HH:mm:ss.fff} (lệch {result.DriftMs:F1}ms)";
        });
    }

    private void BtnOffset_Click(object sender, RoutedEventArgs e)
    {
        if (_settingsService?.Settings == null) return;
        if (sender is Button btn && int.TryParse(btn.Tag?.ToString(), out int deltaMs))
        {
            _settingsService.Settings.DelayOffsetMs += deltaMs * 10;
            _settingsService.SaveSettings();
            UpdateDelayLabel();
        }
    }

    private void TxtDefaultWaitSec_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_settingsService?.Settings == null) return;
        if (double.TryParse(TxtDefaultWaitSec?.Text, out double val))
        {
            _settingsService.Settings.DefaultWaitSec = val;
            _settingsService.SaveSettings();
        }
    }

    private void ChkAutoClick_Changed(object sender, RoutedEventArgs e)
    {
        if (_settingsService?.Settings == null) return;
        _settingsService.Settings.AutoClickEnabled = ChkAutoClick.IsChecked == true;
        _settingsService.SaveSettings();
    }

    private void TxtClickCoords_TextChanged(object sender, TextChangedEventArgs e)
    {
        if (_settingsService?.Settings == null) return;
        if (int.TryParse(TxtClickX?.Text, out int x) && int.TryParse(TxtClickY?.Text, out int y))
        {
            _settingsService.Settings.ClickX = x;
            _settingsService.Settings.ClickY = y;
            _settingsService.SaveSettings();
        }
    }

    private void BtnPickPoint_Click(object sender, RoutedEventArgs e)
    {
        Hide();
        try
        {
            var picker = new PickPointWindow();
            if (picker.ShowDialog() == true && picker.SelectedPoint.HasValue)
            {
                int x = (int)picker.SelectedPoint.Value.X;
                int y = (int)picker.SelectedPoint.Value.Y;
                TxtClickX.Text = x.ToString();
                TxtClickY.Text = y.ToString();
                _settingsService.Settings.ClickX = x;
                _settingsService.Settings.ClickY = y;
                _settingsService.SaveSettings();
                _logger.Log("click", $"Đã chọn vị trí click ({x}, {y})");
            }
        }
        finally
        {
            Show();
            Activate();
        }
    }

    private void BtnTestClick_Click(object sender, RoutedEventArgs e)
    {
        int x = _settingsService.Settings.ClickX;
        int y = _settingsService.Settings.ClickY;

        if (x <= 0 && y <= 0)
        {
            MessageBox.Show("Vui lòng nhập hoặc chọn tọa độ X, Y trước khi test!", "Test click", MessageBoxButton.OK, MessageBoxImage.Warning);
            return;
        }

        _logger.Log("click", $"Test click tại ({x}, {y})");
        bool ok = Win32Native.PerformClick(x, y);
        if (ok)
        {
            TxtStatus.Text = $"Đã test click tại ({x}, {y}) thành công.";
        }
        else
        {
            TxtStatus.Text = $"Test click yêu cầu chạy trên hệ điều hành Windows.";
        }
    }

    private void BtnOpenLogFolder_Click(object sender, RoutedEventArgs e)
    {
        try
        {
            Process.Start(new ProcessStartInfo
            {
                FileName = _logger.LogDirectory,
                UseShellExecute = true
            });
        }
        catch { }
    }

    private void BtnClearLog_Click(object sender, RoutedEventArgs e)
    {
        _logger.ClearUI();
        _logLines.Clear();
        TxtLogArea.Text = "";
    }
}
