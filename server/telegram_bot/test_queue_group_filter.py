import unittest
import tempfile
from pathlib import Path
from db import ChatDatabase

class QueueGroupFilterTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = str(Path(self.temp_dir.name) / "test.db")
        self.db = ChatDatabase(db_path)
        self.db.init_schema()

        # Create 2 rooms
        self.room1_id = self.db.upsert_chat_room(
            platform="telegram", chat_id="-100111", chat_type="channel", title="Nhóm A"
        )
        self.room2_id = self.db.upsert_chat_room(
            platform="telegram", chat_id="-100222", chat_type="channel", title="Nhóm B"
        )

        # Add messages and queue items
        msg1_id = self.db.insert_chat_message(
            room_id=self.room1_id,
            user_id=None,
            platform_message_id="1001",
            direction="incoming",
            text="Tin tu Nhom A",
        )
        self.db.enqueue_message(
            room_id=self.room1_id,
            message_id=msg1_id,
            priority=10,
            max_attempts=3,
            payload={"url": "https://example.com/a"},
        )

        msg2_id = self.db.insert_chat_message(
            room_id=self.room2_id,
            user_id=None,
            platform_message_id="1002",
            direction="incoming",
            text="Tin tu Nhom B",
        )
        self.db.enqueue_message(
            room_id=self.room2_id,
            message_id=msg2_id,
            priority=10,
            max_attempts=3,
            payload={"url": "https://example.com/b"},
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_get_queue_items_all(self):
        items = self.db.get_queue_items(limit=10)
        self.assertEqual(len(items), 2)

    def test_get_queue_items_by_chat_id(self):
        items_a = self.db.get_queue_items(limit=10, group="-100111")
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0]["room"]["chat_id"], "-100111")

        items_b = self.db.get_queue_items(limit=10, group="-100222")
        self.assertEqual(len(items_b), 1)
        self.assertEqual(items_b[0]["room"]["chat_id"], "-100222")

    def test_get_queue_items_by_title(self):
        items_a = self.db.get_queue_items(limit=10, group="Nhóm A")
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0]["room"]["title"], "Nhóm A")

if __name__ == "__main__":
    unittest.main()
