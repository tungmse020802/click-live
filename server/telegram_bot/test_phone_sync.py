#!/usr/bin/env python3
"""Multi-phone queue sync: every device should receive the same jobs in the same order."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from db import ChatDatabase
from phone_push import pop_phone_open, push_phone_open
from phone_registry import list_devices, next_pending_job_for_device, register_device


DEEPLINK = "snssdk1180://live?room_id=7661276816681831176"


class PhoneSyncTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        self.db_path = root / "test.sqlite3"
        self.devices_path = root / "phone_devices.json"
        os.environ["PHONE_DEVICES_FILE"] = str(self.devices_path)
        os.environ["PHONE_SYNC_BROADCAST"] = "true"
        os.environ["PHONE_SYNC_LEAD_SECONDS"] = "2.5"
        self.db = ChatDatabase(str(self.db_path))
        self.db.init_schema()
        self.room_id = self.db.upsert_chat_room("telegram", "-100test", "group", "Test")
        self.devices = [f"phone-{index}" for index in range(1, 6)]
        for device_id in self.devices:
            register_device(device_id, label=device_id)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()
        os.environ.pop("PHONE_DEVICES_FILE", None)

    def _enqueue(self, room_suffix: str) -> int:
        message_id = self.db.insert_chat_message_if_new(
            room_id=self.room_id,
            user_id=None,
            platform_message_id=f"test:{room_suffix}",
            direction="incoming",
            text=f"## test › {room_suffix}\n› {DEEPLINK}",
        )
        assert message_id is not None
        return self.db.enqueue_message(
            message_id=message_id,
            room_id=self.room_id,
            priority=100,
            payload={"deeplink": DEEPLINK, "room_id": "7661276816681831176"},
            max_attempts=3,
        )

    def _poll_job(self, device_id: str, after_id: int = 0) -> Optional[Dict[str, object]]:
        return next_pending_job_for_device(device_id, after_id, self.db)

    def test_all_devices_receive_same_first_job(self) -> None:
        first_id = self._enqueue("job-a")
        seen: Dict[str, int] = {}
        for device_id in self.devices:
            job = self._poll_job(device_id, after_id=0)
            self.assertIsNotNone(job, device_id)
            assert job is not None
            seen[device_id] = int(job["id"])
            self.assertEqual(job["url"], DEEPLINK)
            self.assertTrue(job.get("sync_broadcast"))

        self.assertEqual(len(set(seen.values())), 1)
        self.assertEqual(next(iter(seen.values())), first_id)

    def test_devices_stay_in_same_order_across_three_jobs(self) -> None:
        job_ids = [self._enqueue(f"job-{index}") for index in range(1, 4)]
        sequences: Dict[str, List[int]] = {device_id: [] for device_id in self.devices}

        after_id = 0
        for _ in range(len(job_ids)):
            round_ids: List[int] = []
            for device_id in self.devices:
                job = self._poll_job(device_id, after_id=after_id)
                self.assertIsNotNone(job, f"{device_id} after_id={after_id}")
                assert job is not None
                round_ids.append(int(job["id"]))
                sequences[device_id].append(int(job["id"]))
            self.assertEqual(len(set(round_ids)), 1)
            after_id = round_ids[0]

        expected = job_ids
        for device_id, seq in sequences.items():
            self.assertEqual(seq, expected, device_id)

    def test_concurrent_poll_same_job(self) -> None:
        job_id = self._enqueue("concurrent")
        results: Dict[str, int] = {}
        lock = threading.Lock()

        def worker(device_id: str) -> None:
            job = self._poll_job(device_id, after_id=0)
            with lock:
                results[device_id] = int(job["id"]) if job else -1

        with ThreadPoolExecutor(max_workers=len(self.devices)) as pool:
            futures = [pool.submit(worker, device_id) for device_id in self.devices]
            for future in as_completed(futures):
                future.result()

        self.assertEqual(len(results), len(self.devices))
        self.assertEqual(set(results.values()), {job_id})

    def test_push_open_link_reaches_all_registered_devices(self) -> None:
        url = "https://example.test/open/live?room_id=123"
        result = push_phone_open(url=url, queue_id=42, time_label="0:30s")
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(result.get("devices") or []), len(self.devices))

        urls = []
        for device_id in self.devices:
            job = pop_phone_open(device_id)
            self.assertIsNotNone(job, device_id)
            assert job is not None
            urls.append(job["url"])
            self.assertEqual(job.get("device_id"), device_id)
        self.assertEqual(set(urls), {url})

    def test_queue_items_remain_pending_in_broadcast_mode(self) -> None:
        job_id = self._enqueue("pending-check")
        for device_id in self.devices:
            self._poll_job(device_id, after_id=0)

        items = self.db.get_queue_items(limit=10, statuses=["pending"])
        pending_ids = [int(item["id"]) for item in items]
        self.assertIn(job_id, pending_ids)


class PhoneSyncHttpTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        os.environ["BOT_DB_PATH"] = str(root / "test.sqlite3")
        os.environ["PHONE_DEVICES_FILE"] = str(root / "phone_devices.json")
        os.environ["PHONE_SYNC_BROADCAST"] = "true"
        os.environ["QUEUE_UI_USERNAME"] = "admin"
        os.environ["QUEUE_UI_PASSWORD"] = "admin"
        os.environ["QUEUE_UI_REFRESH_SECONDS"] = "3"

        from queue_ui import QueueUiHandler, load_queue_ui_config

        self.config = load_queue_ui_config()
        self.db = ChatDatabase(self.config.db_path)
        self.db.init_schema()
        self.room_id = self.db.upsert_chat_room("telegram", "-100http", "group", "HTTP")

        class Handler(QueueUiHandler):
            config = self.config
            db = self.db

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self._tmpdir.cleanup()

    def _get_json(self, path: str) -> dict:
        with urlopen(f"{self.base}{path}", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request = Request(
            f"{self.base}{path}",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_http_next_job_multi_device(self) -> None:
        for index in range(1, 4):
            self._post_json("/api/phone/register", {"device_id": f"http-phone-{index}"})

        message_id = self.db.insert_chat_message_if_new(
            room_id=self.room_id,
            user_id=None,
            platform_message_id="http:1",
            direction="incoming",
            text=f"test\n› {DEEPLINK}",
        )
        assert message_id is not None
        queue_id = self.db.enqueue_message(
            message_id=message_id,
            room_id=self.room_id,
            priority=100,
            payload={"deeplink": DEEPLINK},
            max_attempts=3,
        )

        job_ids = []
        for index in range(1, 4):
            query = urlencode({"device_id": f"http-phone-{index}", "after_id": "0", "wait": "0"})
            data = self._get_json(f"/api/phone/next-job?{query}")
            job = data.get("job")
            self.assertIsNotNone(job, data)
            job_ids.append(int(job["id"]))  # type: ignore[index]

        self.assertEqual(set(job_ids), {queue_id})


if __name__ == "__main__":
    unittest.main(verbosity=2)
