using System.Windows;

namespace AutomationDotNet;

public partial class App : Application
{
    protected override void OnStartup(StartupEventArgs e)
    {
        base.OnStartup(e);

        AppDomain.CurrentDomain.UnhandledException += (s, args) =>
        {
            var ex = args.ExceptionObject as Exception;
            MessageBox.Show($"Lỗi ứng dụng: {ex?.Message}\n\n{ex?.StackTrace}", "Lỗi Fatal", MessageBoxButton.OK, MessageBoxImage.Error);
        };

        DispatcherUnhandledException += (s, args) =>
        {
            MessageBox.Show($"Lỗi giao diện WPF: {args.Exception.Message}\n\n{args.Exception.StackTrace}", "Lỗi WPF", MessageBoxButton.OK, MessageBoxImage.Error);
            args.Handled = true;
        };
    }
}
