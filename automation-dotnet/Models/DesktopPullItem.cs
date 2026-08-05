using System.Text.Json.Serialization;

namespace AutomationDotNet.Models;

public class DesktopPullItem
{
    [JsonPropertyName("url")]
    public string Url { get; set; } = "";

    [JsonPropertyName("ttl_seconds")]
    public double TtlSeconds { get; set; } = 30;

    [JsonPropertyName("job_id")]
    public object? JobId { get; set; }

    [JsonPropertyName("click_after_ms")]
    public double ClickAfterMs { get; set; } = 0;

    [JsonPropertyName("time_label")]
    public string TimeLabel { get; set; } = "";

    [JsonPropertyName("queued_at_ms")]
    public double? QueuedAtMs { get; set; }

    [JsonPropertyName("end_time_ms")]
    public double? EndTimeMs { get; set; }
}

public class DesktopPullResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    [JsonPropertyName("queue_user")]
    public string? QueueUser { get; set; }

    [JsonPropertyName("opens")]
    public List<DesktopPullItem>? Opens { get; set; }
}

public class DesktopLoginResponse
{
    [JsonPropertyName("ok")]
    public bool Ok { get; set; }

    [JsonPropertyName("error")]
    public string? Error { get; set; }

    [JsonPropertyName("user")]
    public string? User { get; set; }

    [JsonPropertyName("username")]
    public string? Username { get; set; }

    [JsonPropertyName("pull_token")]
    public string? PullToken { get; set; }

    public string? ResolvedUser => !string.IsNullOrWhiteSpace(User) ? User : Username;
}
