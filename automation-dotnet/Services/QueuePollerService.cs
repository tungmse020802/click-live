using System.Net.Http;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using AutomationDotNet.Models;

namespace AutomationDotNet.Services;

public class QueuePollerService
{
    private readonly HttpClient _client;
    private readonly LoggerService _logger;
    private CancellationTokenSource? _cts;
    private bool _isPolling;

    public event Action<DesktopPullItem>? OnNewJobArrived;
    public event Action<string>? OnAuthStatusChanged;

    public bool IsAuthenticated { get; private set; }
    public string ActiveUser { get; private set; } = "";

    public QueuePollerService(LoggerService logger)
    {
        _logger = logger;
        _client = new HttpClient
        {
            Timeout = TimeSpan.FromSeconds(8)
        };
    }

    public async Task<bool> LoginAsync(string queueUrl, string username, string password)
    {
        try
        {
            var baseUri = queueUrl.TrimEnd('/');
            if (string.IsNullOrEmpty(baseUri)) throw new Exception("URL queue server không hợp lệ");
            if (string.IsNullOrEmpty(username) || string.IsNullOrEmpty(password)) throw new Exception("Vui lòng nhập Username và Password");

            var loginUrl = $"{baseUri}/api/desktop/auth/login";
            var jsonPayload = JsonSerializer.Serialize(new { username, password });
            var content = new StringContent(jsonPayload, Encoding.UTF8, "application/json");

            var response = await _client.PostAsync(loginUrl, content);
            var responseJson = await response.Content.ReadAsStringAsync();
            var result = JsonSerializer.Deserialize<DesktopLoginResponse>(responseJson);

            if (result == null || !result.Ok || string.IsNullOrEmpty(result.PullToken))
            {
                throw new Exception(result?.Error ?? "Đăng nhập thất bại");
            }

            IsAuthenticated = true;
            ActiveUser = result.User ?? username;
            OnAuthStatusChanged?.Invoke(ActiveUser);
            _logger.Log("auth", $"Đăng nhập thành công user={ActiveUser}");
            return true;
        }
        catch (Exception ex)
        {
            IsAuthenticated = false;
            ActiveUser = "";
            OnAuthStatusChanged?.Invoke("");
            _logger.Log("error", "Đăng nhập thất bại", ex.Message);
            throw;
        }
    }

    public void StartPolling(string queueUrl, string pullToken, string queueUsername, int intervalMs = 2000)
    {
        StopPolling();
        if (string.IsNullOrEmpty(queueUrl) || string.IsNullOrEmpty(pullToken))
        {
            _logger.Log("poll", "Chưa đăng nhập — Poller tạm dừng");
            return;
        }

        _cts = new CancellationTokenSource();
        _isPolling = true;
        var token = _cts.Token;
        var baseUri = queueUrl.TrimEnd('/');

        Task.Run(async () =>
        {
            while (!token.IsCancellationRequested && _isPolling)
            {
                try
                {
                    var pollUrl = $"{baseUri}/api/desktop/pull?token={Uri.EscapeDataString(pullToken)}";
                    var data = await _client.GetFromJsonAsync<DesktopPullResponse>(pollUrl, token);

                    if (data != null && data.Ok && data.Opens != null && data.Opens.Count > 0)
                    {
                        var lastItem = data.Opens.Last();
                        _logger.Log("poll", "Pull job mới", $"JobId={lastItem.JobId}, clickAfterMs={lastItem.ClickAfterMs}, timeLabel={lastItem.TimeLabel}");
                        OnNewJobArrived?.Invoke(lastItem);
                    }
                }
                catch (OperationCanceledException) { break; }
                catch (Exception ex)
                {
                    _logger.Log("poll", "Poll lỗi", ex.Message);
                }

                await Task.Delay(intervalMs, token);
            }
        }, token);
    }

    public void StopPolling()
    {
        _isPolling = false;
        _cts?.Cancel();
        _cts?.Dispose();
        _cts = null;
    }
}
