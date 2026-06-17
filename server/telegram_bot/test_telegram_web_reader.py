import unittest

from telegram_web_reader import _is_recent_message


class RecentMessageTest(unittest.TestCase):
    def test_accepts_message_within_five_minutes(self) -> None:
        now_ms = 1_000_000
        self.assertTrue(_is_recent_message(now_ms - 299_000, 300, now_ms))
        self.assertTrue(_is_recent_message(now_ms - 300_000, 300, now_ms))

    def test_rejects_stale_future_or_missing_timestamp(self) -> None:
        now_ms = 1_000_000
        self.assertFalse(_is_recent_message(now_ms - 300_001, 300, now_ms))
        self.assertFalse(_is_recent_message(now_ms + 1, 300, now_ms))
        self.assertFalse(_is_recent_message(None, 300, now_ms))


if __name__ == "__main__":
    unittest.main()
