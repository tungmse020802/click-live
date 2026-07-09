#!/usr/bin/env python3
"""HTTP API: junb.io.vn / thanhtai.io shortlink -> TikTok live deeplink."""

from __future__ import annotations

import json
import os
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from junb_decoder import decode_live_url, extract_encoded_param

HOST = os.environ.get("DEEPLINK_API_HOST", os.environ.get("JUNB_API_HOST", "127.0.0.1"))
PORT = int(os.environ.get("DEEPLINK_API_PORT", os.environ.get("JUNB_API_PORT", "8792")))
DEEPLINK_SCHEME = "snssdk1180://live?room_id="
ROOM_ID_PATTERN = re.compile(r"^\d{5,25}$")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, status: int, html: str) -> None:
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def _room_id_from_query(query: dict[str, list[str]]) -> str:
    room_id = (query.get("room_id") or [""])[0].strip()
    deeplink = (query.get("deeplink") or [""])[0].strip()
    if not room_id and deeplink:
        match = re.search(r"room_id=(\d+)", deeplink)
        if match:
            room_id = match.group(1)
    if not ROOM_ID_PATTERN.match(room_id):
        raise ValueError("Invalid or missing room_id")
    return room_id


def _live_deeplink(room_id: str) -> str:
    return f"{DEEPLINK_SCHEME}{room_id}"


def _open_live_html(room_id: str) -> str:
    deeplink = _live_deeplink(room_id)
    safe_deeplink = deeplink.replace("&", "&amp;").replace('"', "&quot;")
    js_deeplink = deeplink.replace("\\", "\\\\").replace('"', '\\"')
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="0;url={safe_deeplink}">
  <title>Mở TikTok Live</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, sans-serif; padding: 24px; }}
    a {{ word-break: break-all; }}
  </style>
  <script>
    (function() {{
      var target = "{js_deeplink}";
      try {{ window.location.replace(target); }} catch (e) {{}}
      setTimeout(function() {{ window.location.href = target; }}, 50);
    }})();
  </script>
</head>
<body>
  <p>Đang mở TikTok Live...</p>
  <p><a href="{safe_deeplink}">{safe_deeplink}</a></p>
</body>
</html>"""


def resolve_deeplink(url: str) -> dict[str, Any]:
    clean_url = url.strip()
    deeplink = decode_live_url(clean_url)
    return {
        "ok": True,
        "url": clean_url,
        "code": extract_encoded_param(clean_url),
        "deeplink": deeplink,
    }


class DeeplinkApiHandler(BaseHTTPRequestHandler):
    server_version = "LiveDeeplinkAPI/1.2"

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[deeplink-api] {self.address_string()} {format % args}")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_open_live(self, query: dict[str, list[str]]) -> None:
        try:
            room_id = _room_id_from_query(query)
        except ValueError as exc:
            _json_response(self, 400, {"ok": False, "error": str(exc)})
            return
        _html_response(self, 200, _open_live_html(room_id))

    def _handle_deeplink(self, url: str) -> None:
        if not url:
            _json_response(self, 400, {"ok": False, "error": "Missing url"})
            return
        try:
            _json_response(self, 200, resolve_deeplink(url))
        except ValueError as exc:
            _json_response(self, 400, {"ok": False, "error": str(exc), "url": url})
        except Exception as exc:
            _json_response(self, 500, {"ok": False, "error": str(exc), "url": url})

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        if parsed.path == "/health":
            _json_response(
                self,
                200,
                {
                    "ok": True,
                    "service": "live-deeplink-api",
                    "supports": ["i.junb.io.vn", "thanhtai.io", "open/live"],
                },
            )
            return

        if parsed.path in ("/open/live", "/open"):
            self._handle_open_live(query)
            return

        if parsed.path not in ("/api/deeplink", "/deeplink"):
            _json_response(self, 404, {"ok": False, "error": "Not found"})
            return

        url = (query.get("url") or [""])[0]
        self._handle_deeplink(url)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path not in ("/api/deeplink", "/deeplink"):
            _json_response(self, 404, {"ok": False, "error": "Not found"})
            return

        try:
            payload = _read_json_body(self)
        except (json.JSONDecodeError, ValueError) as exc:
            _json_response(self, 400, {"ok": False, "error": f"Invalid JSON: {exc}"})
            return

        url = str(payload.get("url") or "").strip()
        self._handle_deeplink(url)


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DeeplinkApiHandler)
    print(f"Live deeplink API listening on http://{HOST}:{PORT}")
    print("GET  /api/deeplink?url=https://i.junb.io.vn/i/?b7YVmORSncRD4")
    print("GET  /open/live?room_id=7660479963724434197")
    print('POST /api/deeplink {"url":"https://thanhtai.io/r/b7YVmORSncRD4"}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
