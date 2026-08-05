using System.Windows;
using System.Windows.Input;

namespace AutomationDotNet;

public partial class PickPointWindow : Window
{
    public Point? SelectedPoint { get; private set; }

    public PickPointWindow()
    {
        InitializeComponent();
    }

    private void Window_MouseDown(object sender, MouseButtonEventArgs e)
    {
        if (e.LeftButton == MouseButtonState.Pressed)
        {
            SelectedPoint = PointToScreen(e.GetPosition(this));
            DialogResult = true;
            Close();
        }
    }

    private void Window_KeyDown(object sender, KeyEventArgs e)
    {
        if (e.Key == Key.Escape)
        {
            DialogResult = false;
            Close();
        }
    }
}
