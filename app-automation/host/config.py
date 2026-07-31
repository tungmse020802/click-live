from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = ROOT / "config.yaml"
EXAMPLE_CONFIG_PATH = ROOT / "config.example.yaml"


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8788


class DeviceConfig(BaseModel):
    udid: str = ""
    wda_port: int = 8100
    go_ios_path: str = ""
    wda_bundle_id: str = "com.clicklive.WebDriverAgentRunner.xctrunner"
    wda_testrunner_bundle_id: str = "com.clicklive.WebDriverAgentRunner.xctrunner"
    wda_xctestconfig: str = "WebDriverAgentRunner.xctest"
    wda_ipa_path: str = ""
    auto_start_wda: bool = False
    auto_start_tunnel: bool = False
    tunnel_userspace: bool = True
    install_ipa_if_missing: bool = True


class AppsConfig(BaseModel):
    expressvpn_bundle_id: str = "com.expressvpn.ExpressVPN"
    tiktok_bundle_id: str = "com.zhiliaoapp.musically"


class ExpressVpnConfig(BaseModel):
    connect_labels: list[str] = Field(default_factory=lambda: ["Connect", "Kết nối", "ON"])
    disconnect_labels: list[str] = Field(default_factory=lambda: ["Disconnect", "Ngắt kết nối", "OFF"])
    connected_texts: list[str] = Field(default_factory=lambda: ["Connected", "Đã kết nối", "Protected"])
    preferred_location: str = ""
    location_search_labels: list[str] = Field(
        default_factory=lambda: ["Choose Location", "Locations", "Chọn vị trí"]
    )
    connect_timeout_seconds: int = 90
    settle_seconds: float = 2.0
    power_button_x_ratio: float = 0.50
    power_button_y_ratio: float = 0.55


class TikTokAccount(BaseModel):
    email: str = ""
    phone: str = ""
    password: str = ""
    username: str = ""


class TikTokSignupConfig(BaseModel):
    method: str = "email"
    birthday: str = "1998-05-12"
    accounts: list[TikTokAccount] = Field(default_factory=list)
    open_labels: list[str] = Field(default_factory=lambda: ["Sign up", "Đăng ký"])
    continue_labels: list[str] = Field(default_factory=lambda: ["Continue", "Next", "Tiếp"])
    email_option_labels: list[str] = Field(
        default_factory=lambda: ["Use phone or email", "Use email", "Email"]
    )
    phone_option_labels: list[str] = Field(
        default_factory=lambda: ["Use phone or email", "Phone", "Số điện thoại"]
    )
    otp_wait_seconds: int = 300
    step_delay_seconds: float = 1.2


class AutomationConfig(BaseModel):
    screenshot_dir: str = "captures"
    job_timeout_seconds: int = 900
    dismiss_alerts: bool = True
    alert_accept_labels: list[str] = Field(
        default_factory=lambda: ["Allow", "OK", "Cho phép", "Đồng ý", "Not Now", "Để sau"]
    )


class AppConfig(BaseModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    device: DeviceConfig = Field(default_factory=DeviceConfig)
    apps: AppsConfig = Field(default_factory=AppsConfig)
    expressvpn: ExpressVpnConfig = Field(default_factory=ExpressVpnConfig)
    tiktok_signup: TikTokSignupConfig = Field(default_factory=TikTokSignupConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)

    @property
    def screenshot_path(self) -> Path:
        path = Path(self.automation.screenshot_dir)
        if not path.is_absolute():
            path = ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {path}")
    return data


def load_config(path: Path | None = None) -> AppConfig:
    config_path = path or DEFAULT_CONFIG_PATH
    if not config_path.exists() and EXAMPLE_CONFIG_PATH.exists():
        config_path = EXAMPLE_CONFIG_PATH
    return AppConfig.model_validate(_load_yaml(config_path))
