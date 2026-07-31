from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from xml.etree import ElementTree as ET

import httpx


LogFn = Callable[[str], None]


def _default_log(message: str) -> None:
    print(message, flush=True)


@dataclass
class ElementHit:
    uid: str
    label: str
    name: str
    value: str
    type: str
    x: float
    y: float
    width: float
    height: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x + self.width / 2.0, self.y + self.height / 2.0)


class WdaError(RuntimeError):
    pass


class WdaClient:
    """Direct WebDriverAgent HTTP client (no Appium)."""

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        log: LogFn | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.log = log or _default_log
        self.session_id: str | None = None
        self.viewport: dict[str, float] | None = None
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        try:
            self.delete_session()
        finally:
            self._client.close()

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float | None = None,
    ) -> Any:
        url = f"{self.base_url}{path}"
        response = self._client.request(
            method,
            url,
            json=body,
            timeout=timeout or self.timeout,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}
        if response.status_code >= 400:
            message = ""
            if isinstance(payload, dict):
                value = payload.get("value")
                if isinstance(value, dict):
                    message = str(value.get("message") or "")
                message = message or str(payload.get("error") or payload.get("raw") or "")
            raise WdaError(f"{response.status_code} {method} {path}: {message or response.text}")
        if isinstance(payload, dict) and "value" in payload:
            return payload["value"]
        return payload

    def status(self) -> Any:
        return self.request("GET", "/status", timeout=3.0)

    def wait_ready(self, timeout_seconds: float = 60.0) -> None:
        deadline = time.time() + timeout_seconds
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                self.status()
                return
            except Exception as exc:  # noqa: BLE001 - poll until ready
                last_error = exc
                time.sleep(0.5)
        raise WdaError(f"WDA not ready at {self.base_url}: {last_error}")

    def create_session(
        self,
        bundle_id: str | None = None,
        *,
        ready_timeout_seconds: float = 20.0,
    ) -> str:
        self.wait_ready(timeout_seconds=ready_timeout_seconds)
        caps: dict[str, Any] = {
            "capabilities": {
                "alwaysMatch": {
                    "platformName": "iOS",
                    "appium:noReset": True,
                    "appium:waitForIdleTimeout": 0,
                }
            }
        }
        if bundle_id:
            caps["capabilities"]["alwaysMatch"]["appium:bundleId"] = bundle_id
        value = self.request("POST", "/session", caps)
        if isinstance(value, dict):
            session_id = value.get("sessionId") or value.get("session_id")
        else:
            session_id = None
        if not session_id:
            # Some WDA builds nest differently.
            raise WdaError(f"WDA session create returned no sessionId: {value}")
        self.session_id = str(session_id)
        try:
            rect = self.request("GET", f"/session/{self.session_id}/window/rect")
            if isinstance(rect, dict):
                self.viewport = {
                    "x": float(rect.get("x") or 0),
                    "y": float(rect.get("y") or 0),
                    "width": float(rect.get("width") or 0),
                    "height": float(rect.get("height") or 0),
                }
        except WdaError as exc:
            self.log(f"[wda] window/rect unavailable: {exc}")
        self.log(f"[wda] session {self.session_id}")
        return self.session_id

    def delete_session(self) -> None:
        if not self.session_id:
            return
        try:
            self.request("DELETE", f"/session/{self.session_id}", timeout=5.0)
        except WdaError:
            pass
        self.session_id = None

    def _session_path(self, suffix: str) -> str:
        if not self.session_id:
            raise WdaError("No active WDA session. Call create_session() first.")
        return f"/session/{self.session_id}{suffix}"

    def activate_app(self, bundle_id: str) -> None:
        self.request("POST", self._session_path("/wda/apps/activate"), {"bundleId": bundle_id})

    def terminate_app(self, bundle_id: str) -> None:
        try:
            self.request(
                "POST",
                self._session_path("/wda/apps/terminate"),
                {"bundleId": bundle_id},
            )
        except WdaError as exc:
            self.log(f"[wda] terminate {bundle_id} skipped: {exc}")

    def active_app(self) -> dict[str, Any]:
        value = self.request("GET", self._session_path("/wda/activeAppInfo"))
        return value if isinstance(value, dict) else {}

    def home(self) -> None:
        self.request("POST", self._session_path("/wda/homescreen"), {})

    def press_button(self, name: str) -> None:
        self.request("POST", self._session_path("/wda/pressButton"), {"name": name})

    def open_url(self, url: str, bundle_id: str | None = None) -> None:
        body: dict[str, Any] = {"url": url}
        if bundle_id:
            body["bundleId"] = bundle_id
        self.request("POST", self._session_path("/url"), body)

    def tap(self, x: float, y: float) -> None:
        self.request("POST", self._session_path("/wda/tap"), {"x": x, "y": y})

    def tap_ratio(self, x_ratio: float, y_ratio: float) -> None:
        if not self.viewport or not self.viewport.get("width") or not self.viewport.get("height"):
            raise WdaError("Viewport unknown; cannot tap by ratio")
        x = self.viewport["x"] + self.viewport["width"] * x_ratio
        y = self.viewport["y"] + self.viewport["height"] * y_ratio
        self.tap(x, y)

    def swipe(
        self,
        from_x: float,
        from_y: float,
        to_x: float,
        to_y: float,
        *,
        duration: float = 0.25,
    ) -> None:
        self.request(
            "POST",
            self._session_path("/wda/dragfromtoforduration"),
            {
                "fromX": from_x,
                "fromY": from_y,
                "toX": to_x,
                "toY": to_y,
                "duration": duration,
            },
        )

    def type_text(self, text: str) -> None:
        self.request("POST", self._session_path("/wda/keys"), {"value": list(text)})

    def screenshot_png(self) -> bytes:
        value = self.request("GET", self._session_path("/screenshot"))
        if isinstance(value, str):
            return base64.b64decode(value)
        if isinstance(value, dict) and value.get("value"):
            return base64.b64decode(str(value["value"]))
        raise WdaError("Unexpected screenshot payload")

    def save_screenshot(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.screenshot_png())
        return path

    def source_xml(self) -> str:
        value = self.request("GET", self._session_path("/source"))
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return str(value.get("value") or value.get("tree") or "")
        return str(value or "")

    def find_elements(self, using: str, value: str) -> list[str]:
        result = self.request(
            "POST",
            self._session_path("/elements"),
            {"using": using, "value": value},
        )
        if not isinstance(result, list):
            return []
        ids: list[str] = []
        for row in result:
            if isinstance(row, dict):
                element_id = row.get("ELEMENT") or row.get("element-6066-11e4-a52e-4f735466cecf")
                if element_id:
                    ids.append(str(element_id))
        return ids

    def click_element(self, element_id: str) -> None:
        self.request("POST", self._session_path(f"/element/{element_id}/click"), {})

    def element_rect(self, element_id: str) -> dict[str, float]:
        value = self.request("GET", self._session_path(f"/element/{element_id}/rect"))
        if not isinstance(value, dict):
            return {}
        return {
            "x": float(value.get("x") or 0),
            "y": float(value.get("y") or 0),
            "width": float(value.get("width") or 0),
            "height": float(value.get("height") or 0),
        }

    def set_value(self, element_id: str, text: str) -> None:
        self.request(
            "POST",
            self._session_path(f"/element/{element_id}/value"),
            {"value": list(text)},
        )

    def clear_element(self, element_id: str) -> None:
        self.request("POST", self._session_path(f"/element/{element_id}/clear"), {})

    def accept_alert(self) -> bool:
        try:
            self.request("POST", self._session_path("/alert/accept"), {})
            return True
        except WdaError:
            return False

    def dismiss_alert(self) -> bool:
        try:
            self.request("POST", self._session_path("/alert/dismiss"), {})
            return True
        except WdaError:
            return False

    def alert_text(self) -> str:
        try:
            value = self.request("GET", self._session_path("/alert/text"))
            return str(value or "")
        except WdaError:
            return ""

    def parse_source_hits(self) -> list[ElementHit]:
        xml = self.source_xml()
        if not xml:
            return []
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            return []
        hits: list[ElementHit] = []

        def walk(node: ET.Element) -> None:
            attrib = node.attrib
            label = attrib.get("label") or ""
            name = attrib.get("name") or ""
            value = attrib.get("value") or ""
            etype = attrib.get("type") or node.tag
            x = float(attrib.get("x") or 0)
            y = float(attrib.get("y") or 0)
            width = float(attrib.get("width") or 0)
            height = float(attrib.get("height") or 0)
            uid = attrib.get("uid") or f"{etype}:{x}:{y}"
            if width > 0 and height > 0:
                hits.append(
                    ElementHit(
                        uid=uid,
                        label=label,
                        name=name,
                        value=value,
                        type=etype,
                        x=x,
                        y=y,
                        width=width,
                        height=height,
                    )
                )
            for child in list(node):
                walk(child)

        walk(root)
        return hits

    def find_by_labels(
        self,
        labels: list[str],
        *,
        contains: bool = True,
        enabled_only: bool = False,
    ) -> ElementHit | None:
        _ = enabled_only
        needles = [label.strip().lower() for label in labels if label and label.strip()]
        if not needles:
            return None
        for hit in self.parse_source_hits():
            hay = " ".join([hit.label, hit.name, hit.value]).strip().lower()
            if not hay:
                continue
            for needle in needles:
                if contains and needle in hay:
                    return hit
                if not contains and hay == needle:
                    return hit
        return None

    def tap_labels(self, labels: list[str], *, contains: bool = True) -> bool:
        # Prefer WDA element finders first (faster), then source tree scan.
        for label in labels:
            if not label:
                continue
            for using, value in (
                ("accessibility id", label),
                ("name", label),
                ("link text", label),
                (
                    "-ios predicate string",
                    f"label CONTAINS[c] '{label}' OR name CONTAINS[c] '{label}' OR value CONTAINS[c] '{label}'",
                ),
            ):
                try:
                    ids = self.find_elements(using, value)
                except WdaError:
                    continue
                if ids:
                    self.click_element(ids[0])
                    self.log(f"[wda] tapped via finder '{label}' ({using})")
                    return True
        hit = self.find_by_labels(labels, contains=contains)
        if not hit:
            return False
        x, y = hit.center
        self.tap(x, y)
        self.log(f"[wda] tapped source hit '{hit.label or hit.name}' at ({x:.0f},{y:.0f})")
        return True

    def page_contains(self, texts: list[str]) -> bool:
        joined = " ".join(texts).strip()
        if not joined:
            return False
        try:
            source = self.source_xml().lower()
        except WdaError:
            return False
        return any(text.lower() in source for text in texts if text)

    def wait_for_texts(self, texts: list[str], timeout_seconds: float = 30.0) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.page_contains(texts):
                return True
            time.sleep(0.8)
        return False

    def wait_and_tap_labels(
        self,
        labels: list[str],
        *,
        timeout_seconds: float = 20.0,
        contains: bool = True,
    ) -> bool:
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.tap_labels(labels, contains=contains):
                return True
            time.sleep(0.7)
        return False

    def dismiss_system_alerts(self, labels: list[str] | None = None) -> int:
        labels = labels or ["Allow", "OK", "Continue", "Not Now", "Cho phép", "Đồng ý", "Để sau"]
        dismissed = 0
        for _ in range(4):
            text = self.alert_text()
            if text:
                if self.accept_alert():
                    dismissed += 1
                    time.sleep(0.3)
                    continue
            if self.tap_labels(labels, contains=True):
                dismissed += 1
                time.sleep(0.3)
                continue
            break
        return dismissed

    def fill_first_text_field(self, text: str) -> bool:
        for using, value in (
            ("class name", "XCUIElementTypeTextField"),
            ("class name", "XCUIElementTypeTextView"),
            ("class name", "XCUIElementTypeSecureTextField"),
        ):
            try:
                ids = self.find_elements(using, value)
            except WdaError:
                continue
            if not ids:
                continue
            element_id = ids[0]
            try:
                self.clear_element(element_id)
            except WdaError:
                pass
            self.click_element(element_id)
            time.sleep(0.2)
            try:
                self.set_value(element_id, text)
            except WdaError:
                self.type_text(text)
            return True
        # Fallback: focused keyboard typing.
        self.type_text(text)
        return True

    def fill_fields_by_index(self, values: list[str]) -> int:
        filled = 0
        ids: list[str] = []
        for using, value in (
            ("class name", "XCUIElementTypeTextField"),
            ("class name", "XCUIElementTypeSecureTextField"),
        ):
            try:
                ids.extend(self.find_elements(using, value))
            except WdaError:
                continue
        # Keep order, drop duplicates.
        seen: set[str] = set()
        ordered: list[str] = []
        for element_id in ids:
            if element_id in seen:
                continue
            seen.add(element_id)
            ordered.append(element_id)
        for element_id, text in zip(ordered, values):
            try:
                self.clear_element(element_id)
            except WdaError:
                pass
            self.click_element(element_id)
            time.sleep(0.15)
            try:
                self.set_value(element_id, text)
            except WdaError:
                self.type_text(text)
            filled += 1
            time.sleep(0.2)
        return filled

    @staticmethod
    def normalize_space(text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()
