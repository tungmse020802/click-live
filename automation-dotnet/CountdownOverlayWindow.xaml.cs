using System.Windows;
using System.Windows.Media;
using AutomationDotNet.Services;

namespace AutomationDotNet;

public partial class CountdownOverlayWindow : Window
{
    private long? _targetAtMs;
    private bool _isActive;
    private double _lastRenderedSec = -1;
    private EventHandler? _renderHandler;

    public CountdownOverlayWindow()
    {
        InitializeComponent();
    }

    public void StartCountdown(long targetAtMs)
    {
        _targetAtMs = targetAtMs;
        _isActive = true;
        _lastRenderedSec = -1;

        if (_renderHandler == null)
        {
            _renderHandler = (_, _) => UpdateDisplay();
            CompositionTarget.Rendering += _renderHandler;
        }

        UpdateDisplay();
    }

    public void StopCountdown()
    {
        _isActive = false;
        _targetAtMs = null;
        _lastRenderedSec = -1;

        if (_renderHandler != null)
        {
            CompositionTarget.Rendering -= _renderHandler;
            _renderHandler = null;
        }

        TxtClock.Text = "--";
        TxtClock.FontSize = 36;
        Width = 300;
        TxtClock.Foreground = new SolidColorBrush(Color.FromArgb(140, 255, 255, 255));
    }

    private void UpdateDisplay()
    {
        if (!_isActive || !_targetAtMs.HasValue)
        {
            TxtClock.Text = "--";
            TxtClock.FontSize = 36;
            Width = 300;
            TxtClock.Foreground = new SolidColorBrush(Color.FromArgb(140, 255, 255, 255));
            return;
        }

        long nowMs = TimingHelper.NowMs();
        double remainingMs = Math.Max(0, _targetAtMs.Value - nowMs);
        double remainingSec = remainingMs / 1000.0;

        if (Math.Abs(remainingSec - _lastRenderedSec) < 0.005)
            return;

        _lastRenderedSec = remainingSec;
        bool longFormat = remainingSec >= 60;

        TxtClock.Text = TimingHelper.FormatRemainingSeconds(remainingSec);
        TxtClock.FontSize = longFormat ? 52 : 64;
        Width = longFormat ? 380 : 300;

        if (remainingMs <= 0)
        {
            TxtClock.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#4ADE80"));
        }
        else if (remainingMs <= 3000)
        {
            TxtClock.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#FCD34D"));
        }
        else
        {
            TxtClock.Foreground = Brushes.White;
        }
    }
}
