import unittest

from time_parse import extract_time_from_text, normalize_time_label


class TimeParseTests(unittest.TestCase):
    def test_normalize_strips_box_junk(self) -> None:
        raw = "01:19s - 23:11:16 🎁  BOX :  50/30 🇦🇪 📈  Rate :"
        self.assertEqual(normalize_time_label(raw), "01:19s - 23:11:16")

    def test_extract_from_message_line(self) -> None:
        text = "## room ⏳ TIME :  00:57s - 22:40:51 🎁 BOX"
        meta = extract_time_from_text(text)
        self.assertEqual(meta["label"], "00:57s - 22:40:51")
        self.assertEqual(meta["target_time_hhmmss"], "22:40:51")
        self.assertEqual(meta["click_after_ms"], 57000)


if __name__ == "__main__":
    unittest.main()
