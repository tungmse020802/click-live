using System.Collections.ObjectModel;
using System.IO;
using System.Windows;
using AutomationDotNet.Models;

namespace AutomationDotNet.Services;

public class LoggerService
{
    private readonly string _logDir;
    private readonly object _fileLock = new();

    public ObservableCollection<LogEntry> UIEntries { get; } = new();
    public string LogDirectory => _logDir;
    public event Action<LogEntry>? OnLogEntryAdded;

    public LoggerService()
    {
        var appData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        _logDir = Path.Combine(appData, "ClickLiveDesktopTool", "logs");
        Directory.CreateDirectory(_logDir);
    }

    public void Log(string eventType, string message, string details = "")
    {
        var entry = new LogEntry
        {
            Timestamp = DateTime.Now,
            EventType = eventType,
            Message = message,
            Details = details
        };

        Application.Current?.Dispatcher.InvokeAsync(() =>
        {
            UIEntries.Insert(0, entry);
            while (UIEntries.Count > 150)
            {
                UIEntries.RemoveAt(UIEntries.Count - 1);
            }
            OnLogEntryAdded?.Invoke(entry);
        });

        try
        {
            var fileName = $"click-{DateTime.Now:yyyy-MM-dd}.log";
            var filePath = Path.Combine(_logDir, fileName);
            var line = $"[{entry.Timestamp:HH:mm:ss.fff}] [{entry.EventType.ToUpper()}] {entry.Message} {entry.Details}\n";
            lock (_fileLock)
            {
                File.AppendAllText(filePath, line);
            }
        }
        catch { }
    }

    public void ClearUI()
    {
        UIEntries.Clear();
    }
}
