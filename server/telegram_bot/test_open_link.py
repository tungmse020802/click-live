import unittest
from unittest.mock import patch

from open_link import open_link_for_queue, phone_open_url


class OpenLinkTests(unittest.TestCase):
    def test_phone_open_url_from_deeplink(self) -> None:
        with patch.dict("os.environ", {"DEEPLINK_OPEN_BASE_URL": "http://127.0.0.1:8792"}):
            url = phone_open_url("snssdk1180://live?room_id=7660546312748108566")
        self.assertEqual(url, "snssdk1180://live?room_id=7660546312748108566")

    @patch("open_link.enqueue_open")
    @patch("open_link._try_open_phone")
    @patch("open_link.resolve_link_for_open")
    def test_open_link_for_queue_desktop_and_phone(
        self,
        resolve_mock,
        phone_mock,
        desktop_mock,
    ) -> None:
        resolve_mock.return_value = {
            "ok": True,
            "source_url": "https://thanhtai.io/r/abc",
            "deeplink": "snssdk1180://live?room_id=7660546312748108566",
            "room_id": "7660546312748108566",
            "countdown_url": "https://thanhtai.io/countdow?data=abc",
            "open_url": "https://thanhtai.io/countdow?data=abc",
        }
        desktop_mock.return_value = {"ok": True, "queued": True}
        phone_mock.return_value = {"ok": True, "method": "phone_monitor"}

        result = open_link_for_queue(
            "https://thanhtai.io/r/abc",
            context="ctx",
            job_id=42,
            click_after_ms=1000,
        )

        self.assertTrue(result["ok"])
        desktop_mock.assert_called_once()
        phone_mock.assert_called_once()
        self.assertIn("phone_open_url", result)


if __name__ == "__main__":
    unittest.main()
