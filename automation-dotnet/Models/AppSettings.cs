using System.Text.Json.Serialization;

namespace AutomationDotNet.Models;

public class AppSettings
{
    [JsonPropertyName("queueUrl")]
    public string QueueUrl { get; set; } = "http://160.30.19.215:8787";

    [JsonPropertyName("queueUsername")]
    public string QueueUsername { get; set; } = "admin";

    [JsonPropertyName("queuePassword")]
    public string QueuePassword { get; set; } = "Admin123@";

    [JsonPropertyName("pullToken")]
    public string PullToken { get; set; } = "";

    [JsonPropertyName("defaultWaitSec")]
    public double DefaultWaitSec { get; set; } = 0.0;

    [JsonPropertyName("delayOffsetMs")]
    public double DelayOffsetMs { get; set; } = 0.0;

    [JsonPropertyName("autoClickEnabled")]
    public bool AutoClickEnabled { get; set; } = true;

    [JsonPropertyName("clickX")]
    public int ClickX { get; set; } = 0;

    [JsonPropertyName("clickY")]
    public int ClickY { get; set; } = 0;
}
