import unittest

from phone_push import pop_phone_open, push_phone_open


class PhonePushTests(unittest.TestCase):
    def test_push_and_pop(self) -> None:
        result = push_phone_open(
            url="snssdk1180://live?room_id=7660546312748108566",
            queue_id=99,
            time_label="1:30s",
            click_after_ms=1500,
        )
        self.assertTrue(result["ok"])
        job = pop_phone_open("device-a")
        self.assertIsNotNone(job)
        assert job is not None
        self.assertLess(job["id"], 0)
        self.assertEqual(job["url"], "snssdk1180://live?room_id=7660546312748108566")
        self.assertGreaterEqual(job["click_after_ms"], 1500)
        self.assertIsNone(pop_phone_open("device-a"))


if __name__ == "__main__":
    unittest.main()
