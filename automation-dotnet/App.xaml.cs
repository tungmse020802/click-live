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
            var realEx = ex?.InnerException ?? ex;
            MessageBox.Show($"Lỗi ứng dụng: {realEx?.Message}\n\n{realEx?.StackTrace}", "Lỗi Fatal", MessageBoxButton.OK, MessageBoxImage.Error);
        };

        DispatcherUnhandledException += (s, args) =>
        {
            var ex = args.Exception;
            var realEx = ex.InnerException ?? ex;
            MessageBox.Show($"Lỗi giao diện WPF: {realEx.Message}\n\n{realEx.StackTrace}", "Lỗi WPF", MessageBoxButton.OK, MessageBoxImage.Error);
            args.Handled = true;
        };
    }
}
