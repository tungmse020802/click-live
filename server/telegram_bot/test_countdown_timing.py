import base64
import json
import unittest

from countdown_timing import normalize_end_time_ms, parse_junb_end_time_ms


class CountdownTimingTests(unittest.TestCase):
    def test_normalize_end_time_seconds(self) -> None:
        self.assertEqual(normalize_end_time_ms(1700000000), 1700000000000)

    def test_parse_junb_end_time(self) -> None:
        payload = {"user": "x", "end_time": 1700000000}
        raw = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
        url = f"https://i.junb.io.vn/box-countdown/index4.html?r={raw}"
        self.assertEqual(parse_junb_end_time_ms(url), 1700000000000)

    def test_parse_junb_without_end_time(self) -> None:
        payload = {"user": "x", "coins": 50}
        raw = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii").rstrip("=")
        url = f"https://i.junb.io.vn/box-countdown/index4.html?r={raw}"
        self.assertIsNone(parse_junb_end_time_ms(url))


if __name__ == "__main__":
    unittest.main()
