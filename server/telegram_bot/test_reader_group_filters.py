"""Per-account watch groups and group filter scope."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from db import ChatDatabase
from message_filter import GroupFilterScope, MessageFilterEngine, parse_box_signal


class ReaderGroupFilterTests(unittest.TestCase):
    def test_watch_groups_scoped_by_reader(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db = ChatDatabase(str(Path(tmp) / "chatbot.sqlite3"))
            db.init_schema()
            db.replace_watch_groups_for_reader(
                "app1",
                [{"name": "Moon", "chat_id": "-1001", "enabled": True}],
            )
            db.replace_watch_groups_for_reader(
                "app2",
                [{"name": "Oliver", "chat_id": "-1002", "enabled": True}],
            )

            app1 = db.list_enabled_watch_groups(reader_id="app1")
            app2 = db.list_enabled_watch_groups(reader_id="app2")
            self.assertEqual(len(app1), 1)
            self.assertEqual(app1[0]["chat_id"], "-1001")
            self.assertEqual(len(app2), 1)
            self.assertEqual(app2[0]["chat_id"], "-1002")

    def test_group_filter_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "filters.json"
            config_path.write_text(
                '{"filters":[{"name":"global","enabled":true,"min_box1":99,"max_box1":99}],"reject":[]}',
                encoding="utf-8",
            )
            engine = MessageFilterEngine(
                enabled=True,
                config_path=str(config_path),
                reload_seconds=0,
                default_priority=100,
            )
            text = "BOX: 50 / 1"

            block_scope = GroupFilterScope(mode="block_all", rules=(), reject_rules=())
            result = engine.evaluate(
                text,
                parse_box_signal(text),
                reader_id="app1",
                group_scope=block_scope,
            )
            self.assertFalse(result.matched)
            self.assertEqual(result.reason, "group_block_all")

            pass_scope = GroupFilterScope(mode="pass_all", rules=(), reject_rules=())
            result = engine.evaluate(
                text,
                parse_box_signal(text),
                reader_id="app1",
                group_scope=pass_scope,
            )
            self.assertTrue(result.matched)
            self.assertEqual(result.reason, "group_pass_all")

            custom_scope = GroupFilterScope.from_db_payload(
                {
                    "mode": "custom",
                    "filters": [
                        {
                            "name": "group",
                            "enabled": True,
                            "min_box1": 50,
                            "max_box1": 50,
                            "min_box2": 1,
                            "max_box2": 1,
                        }
                    ],
                    "reject": [],
                }
            )
            result = engine.evaluate(
                text,
                parse_box_signal(text),
                reader_id="app1",
                group_scope=custom_scope,
            )
            self.assertTrue(result.matched)

            result = engine.evaluate(
                text,
                parse_box_signal(text),
                reader_id="app1",
            )
            self.assertFalse(result.matched)


if __name__ == "__main__":
    unittest.main()
