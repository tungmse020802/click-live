#!/usr/bin/env python3
import json
import os
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

import queue_ui
from db import ChatDatabase


class ClientFiltersDataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._path = Path(self._tmpdir.name) / "client_message_filters.json"
        self._orig_path = queue_ui.CLIENT_FILTERS_PATH
        queue_ui.CLIENT_FILTERS_PATH = self._path

    def tearDown(self) -> None:
        queue_ui.CLIENT_FILTERS_PATH = self._orig_path
        self._tmpdir.cleanup()

    def test_load_defaults_when_missing(self) -> None:
        data = queue_ui._load_client_filters_data()
        self.assertTrue(data["enabled"])
        self.assertEqual(data["filters"], [])
        self.assertEqual(data["reject"], [])
        self.assertEqual(data["exclude_telegram_groups"], [])

    def test_save_and_load_roundtrip(self) -> None:
        payload = {
            "enabled": True,
            "filters": [
                {
                    "name": "client_box_20_16",
                    "enabled": True,
                    "min_box1": 20,
                    "max_box1": 20,
                    "min_box2": 16,
                    "max_box2": 16,
                    "text_contains": ["có thể treo"],
                }
            ],
            "reject": [
                {
                    "name": "block_sun_comment",
                    "enabled": True,
                    "comment_contains": ["\u0489"],
                }
            ],
            "exclude_telegram_groups": ["-3734576353"],
        }
        saved = queue_ui._save_client_filters_data(payload)
        self.assertEqual(saved["filters"][0]["min_box1"], 20)
        self.assertEqual(saved["reject"][0]["comment_contains"], ["\u0489"])
        self.assertEqual(saved["exclude_telegram_groups"], ["-3734576353"])

        loaded = queue_ui._load_client_filters_data()
        self.assertEqual(loaded["filters"][0]["name"], "client_box_20_16")
        self.assertEqual(loaded["reject"][0]["name"], "block_sun_comment")

    def test_load_corrupt_file_returns_defaults(self) -> None:
        self._path.write_text("{not json", encoding="utf-8")
        data = queue_ui._load_client_filters_data()
        self.assertEqual(data["filters"], [])

    def test_save_rejects_invalid_filters(self) -> None:
        with self.assertRaises(ValueError):
            queue_ui._save_client_filters_data({"filters": "bad"})


class ClientFiltersHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        os.environ["BOT_DB_PATH"] = str(root / "test.sqlite3")
        os.environ["QUEUE_UI_USERNAME"] = "admin"
        os.environ["QUEUE_UI_PASSWORD"] = "Admin123@"
        os.environ["QUEUE_UI_AUTH_ENABLED"] = "true"

        self._orig_client_path = queue_ui.CLIENT_FILTERS_PATH
        queue_ui.CLIENT_FILTERS_PATH = root / "client_message_filters.json"

        from queue_ui import QueueUiHandler, load_queue_ui_config

        self.config = load_queue_ui_config()
        self.db = ChatDatabase(self.config.db_path)
        self.db.init_schema()

        class Handler(QueueUiHandler):
            config = self.config
            db = self.db

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"
        self.opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def tearDown(self) -> None:
        self.server.shutdown()
        queue_ui.CLIENT_FILTERS_PATH = self._orig_client_path
        self._tmpdir.cleanup()

    def _login(self) -> None:
        body = json.dumps({"username": "admin", "password": "Admin123@"}).encode("utf-8")
        request = Request(
            f"{self.base}/api/auth/login",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.opener.open(request, timeout=10) as response:
            payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload.get("ok"))

    def _get_json(self, path: str) -> dict:
        with self.opener.open(f"{self.base}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> tuple[int, dict]:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener.open(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raw = exc.read().decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"error": raw}
            return exc.code, data

    def test_client_filters_page_requires_login(self) -> None:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("GET", "/client-filters")
        response = conn.getresponse()
        conn.close()
        self.assertEqual(response.status, 302)
        self.assertIn("/login", response.getheader("Location", ""))

    def test_client_filters_page_html(self) -> None:
        self._login()
        request = Request(f"{self.base}/client-filters")
        with self.opener.open(request, timeout=10) as response:
            html = response.read().decode("utf-8")
        self.assertIn("Setup Client Filter", html)
        self.assertIn("/api/client-filters", html)
        self.assertIn("Client (trình duyệt)", html)
        self.assertNotIn("fetch('/api/filters?reader_id=", html)

    def test_get_api_client_filters(self) -> None:
        self._login()
        data = self._get_json("/api/client-filters")
        self.assertIn("filters", data)
        self.assertIn("path", data)

    def test_post_api_client_filters_persists(self) -> None:
        self._login()
        payload = {
            "filters": [
                {
                    "name": "http_client_filter",
                    "enabled": True,
                    "min_box1": 50,
                    "max_box1": 50,
                    "text_contains": ["Rương treo"],
                }
            ],
            "reject": [],
            "exclude_telegram_groups": [],
        }
        status, saved = self._post_json("/api/client-filters", payload)
        self.assertEqual(status, 200)
        self.assertEqual(saved["filters"][0]["name"], "http_client_filter")

        loaded = self._get_json("/api/client-filters")
        self.assertEqual(loaded["filters"][0]["min_box1"], 50)

        on_disk = json.loads(queue_ui.CLIENT_FILTERS_PATH.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["filters"][0]["text_contains"], ["Rương treo"])

    def test_post_api_client_filters_requires_auth(self) -> None:
        status, data = self._post_json("/api/client-filters", {"filters": []})
        self.assertEqual(status, 401)
        self.assertIn("error", data)


if __name__ == "__main__":
    unittest.main(verbosity=2)
