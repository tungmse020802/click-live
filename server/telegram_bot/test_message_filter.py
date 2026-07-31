#!/usr/bin/env python3
import tempfile
import unittest
from pathlib import Path

from message_filter import MessageFilterEngine, SUN_MARKER, parse_box_signal


SAMPLE_CLEAN = """##  BT25754 › clean
⏳ TIME :  00:57s
🟪  BAG :  50/1 🏅🇦🇪
📈  Rate :  50.0 (RST)   👀 4
🎯  Level:  1   👤 0
💬  ‎ماشاءالله ولا قوه إلا بالله❤️
› snssdk1180://live?room_id=7661276816681831176
"""

SAMPLE_SUN = """##  BT25754 › sun
⏳ TIME :  00:57s
🟪  BAG :  50/1 🏅🇦🇪
📈  Rate :  50.0 (RST)   👀 4
🎯  Level:  1   👤 0
💬  ‎ماشاءالله ولا قوه إلا بالله❤️ ‟҉
› snssdk1180://live?room_id=7661276816681831176
"""

SAMPLE_LOW = """##  BT1 › low
⏳ TIME :  00:10s
🟪  BAG :  10/1 🏅🇦🇪
📈  Rate :  2.0   👀 4
🎯  Level:  0   👤 0
"""


class MessageFilterRejectTests(unittest.TestCase):
    def _engine(self, payload: dict) -> MessageFilterEngine:
        tmp = Path(tempfile.mkdtemp()) / "message_filters.json"
        tmp.write_text(__import__("json").dumps(payload, ensure_ascii=False), encoding="utf-8")
        return MessageFilterEngine(
            enabled=True,
            config_path=str(tmp),
            reload_seconds=0,
            default_priority=100,
        )

    def test_parse_bag_signal(self) -> None:
        signal = parse_box_signal(SAMPLE_CLEAN)
        self.assertIsNotNone(signal)
        assert signal is not None
        self.assertEqual(signal.box, "50/1")
        self.assertEqual(signal.box_left, 50)
        self.assertEqual(signal.box_right, 1)
        self.assertEqual(signal.rate, 50.0)
        self.assertEqual(signal.level, 1)

    def test_reject_sun_marker_on_comment(self) -> None:
        engine = self._engine(
            {
                "filters": [],
                "reject": [
                    {
                        "name": "block_sun_comment",
                        "enabled": True,
                        "comment_contains": [SUN_MARKER],
                    }
                ],
            }
        )
        blocked = engine.evaluate(SAMPLE_SUN)
        allowed = engine.evaluate(SAMPLE_CLEAN)
        self.assertFalse(blocked.matched)
        self.assertIn("rejected", blocked.reason)
        self.assertTrue(allowed.matched)

    def test_empty_config_allows_all(self) -> None:
        engine = self._engine({"filters": [], "reject": []})
        self.assertTrue(engine.evaluate(SAMPLE_SUN).matched)
        self.assertTrue(engine.evaluate(SAMPLE_CLEAN).matched)

    def test_empty_filter_fields_allow_any_message(self) -> None:
        engine = self._engine(
            {
                "filters": [{"name": "open", "enabled": True}],
                "reject": [],
            }
        )
        self.assertTrue(engine.evaluate(SAMPLE_CLEAN).matched)
        self.assertTrue(engine.evaluate(SAMPLE_LOW).matched)
        plain = "hello without box signal"
        self.assertTrue(engine.evaluate(plain).matched)

    def test_global_exclude_telegram_group(self) -> None:
        engine = self._engine(
            {
                "exclude_telegram_groups": ["-1003734576353", "Moon_bad"],
                "filters": [
                    {
                        "name": "any_box",
                        "enabled": True,
                        "min_box1": 50,
                    }
                ],
                "reject": [],
            }
        )
        blocked = engine.evaluate(
            SAMPLE_CLEAN,
            chat_id="-1003734576353",
            chat_label="Moon_bad",
        )
        allowed = engine.evaluate(
            SAMPLE_CLEAN,
            chat_id="-100111222333",
            chat_label="Moon_ok",
        )
        self.assertFalse(blocked.matched)
        self.assertEqual(blocked.reason, "excluded_telegram_group")
        self.assertTrue(allowed.matched)

    def test_telegram_group_filter(self) -> None:
        engine = self._engine(
            {
                "filters": [
                    {
                        "name": "moon_only",
                        "enabled": True,
                        "min_box1": 50,
                        "telegram_groups": ["-1003734576353", "Moon_2"],
                    }
                ],
                "reject": [],
            }
        )
        matched = engine.evaluate(
            SAMPLE_CLEAN,
            chat_id="-1003734576353",
            chat_label="Moon_2",
        )
        blocked = engine.evaluate(
            SAMPLE_CLEAN,
            chat_id="-1009999999999",
            chat_label="Other",
        )
        self.assertTrue(matched.matched)
        self.assertFalse(blocked.matched)
        self.assertEqual(blocked.reason, "telegram_group")

    def test_telegram_group_empty_means_all_groups(self) -> None:
        engine = self._engine(
            {
                "filters": [
                    {
                        "name": "any_group",
                        "enabled": True,
                        "min_box1": 50,
                    }
                ],
                "reject": [],
            }
        )
        self.assertTrue(
            engine.evaluate(SAMPLE_CLEAN, chat_id="-100111", chat_label="A").matched
        )
        self.assertTrue(
            engine.evaluate(SAMPLE_CLEAN, chat_id="-100222", chat_label="B").matched
        )

    def test_text_contains_or_phrase(self) -> None:
        engine = self._engine(
            {
                "filters": [
                    {
                        "name": "treo",
                        "enabled": True,
                        "text_contains": ["có thể treo", "Rương treo"],
                    }
                ],
                "reject": [],
            }
        )
        hit = "## BT › x\n🧤 Rương treo x‌‌\n› snssdk1180://live?room_id=1"
        miss = "## BT › x\n🧤 normal box\n› snssdk1180://live?room_id=1"
        self.assertTrue(engine.evaluate(hit).matched)
        self.assertFalse(engine.evaluate(miss).matched)

    def test_text_contains_without_box_signal(self) -> None:
        engine = self._engine(
            {
                "filters": [
                    {
                        "name": "phrase_only",
                        "enabled": True,
                        "text_contains": ["có thể treo"],
                    }
                ],
                "reject": [],
            }
        )
        self.assertTrue(engine.evaluate("tin nhắn có thể treo ngay").matched)
        self.assertFalse(engine.evaluate("tin nhắn khác").matched)

    def test_range_filters_bag_rate_level(self) -> None:
        engine = self._engine(
            {
                "filters": [
                    {
                        "name": "exact_sample",
                        "enabled": True,
                        "min_box1": 50,
                        "max_box1": 50,
                        "min_box2": 1,
                        "max_box2": 1,
                        "min_rate": 50,
                        "max_rate": 50,
                        "min_level": 1,
                        "max_level": 1,
                    }
                ],
                "reject": [],
            }
        )
        self.assertTrue(engine.evaluate(SAMPLE_CLEAN).matched)
        self.assertFalse(engine.evaluate(SAMPLE_LOW).matched)


if __name__ == "__main__":
    unittest.main()
