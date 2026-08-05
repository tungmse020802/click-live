using System.Windows;
using System.Windows.Media;
using System.Windows.Threading;

namespace AutomationDotNet;

public partial class CountdownOverlayWindow : Window
{
    private readonly DispatcherTimer _renderTimer;
    private DateTime? _targetTime;
    private bool _isActive;

    public CountdownOverlayWindow()
    {
        InitializeComponent();

        _renderTimer = new DispatcherTimer(DispatcherPriority.Render)
        {
            Interval = TimeSpan.FromMilliseconds(16) // ~60fps
        };
        _renderTimer.Tick += RenderTimer_Tick;
    }

    public void StartCountdown(DateTime targetDisplayTime)
    {
        _targetTime = targetDisplayTime;
        _isActive = true;

        if (!_renderTimer.IsEnabled)
        {
            _renderTimer.Start();
        }

        UpdateDisplay();
    }

    public void StopCountdown()
    {
        _isActive = false;
        _targetTime = null;
        _renderTimer.Stop();

        Dispatcher.Invoke(() =>
        {
            TxtClock.Text = "--";
            TxtClock.FontSize = 36;
            TxtClock.Foreground = new SolidColorBrush(Color.FromArgb(140, 255, 255, 255));
        });
    }

    private void RenderTimer_Tick(object? sender, EventArgs e)
    {
        UpdateDisplay();
    }

    private void UpdateDisplay()
    {
        if (!_isActive || !_targetTime.HasValue)
        {
            TxtClock.Text = "--";
            TxtClock.FontSize = 36;
            TxtClock.Foreground = new SolidColorBrush(Color.FromArgb(140, 255, 255, 255));
            return;
        }

        double remainingMs = (_targetTime.Value - DateTime.Now).TotalMilliseconds;
        double remainingSec = Math.Max(0, remainingMs / 1000.0);

        TxtClock.Text = remainingSec.ToString("F2");
        TxtClock.FontSize = 64;

        if (remainingMs <= 0)
        {
            TxtClock.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#4ADE80")); // Green
        }
        else if (remainingMs <= 3000)
        {
            TxtClock.Foreground = new SolidColorBrush((Color)ColorConverter.ConvertFromString("#FCD34D")); // Yellow
        }
        else
        {
            TxtClock.Foreground = Brushes.White;
        }
    }
}
