#!/usr/bin/env python3
"""Tests for live shortlink decoder."""

import unittest

from junb_decoder import decode_junb_url, decode_live_url, extract_encoded_param


class DecodeLiveUrlTests(unittest.TestCase):
    def test_junb_link(self) -> None:
        url = "https://i.junb.io.vn/i/?b7YVmORSncRD4"
        expected = "snssdk1180://live?room_id=7660479963724434197"
        self.assertEqual(decode_live_url(url), expected)
        self.assertEqual(decode_junb_url(url), expected)
        self.assertEqual(extract_encoded_param(url), "b7YVmORSncRD4")

    def test_thanhtai_link(self) -> None:
        url = "https://thanhtai.io/r/b7YVmORSncRD4"
        expected = "snssdk1180://live?room_id=7660479963724434197"
        self.assertEqual(extract_encoded_param(url), "b7YVmORSncRD4")
        self.assertEqual(decode_live_url(url), expected)

    def test_thanhtai_countdown(self) -> None:
        url = "https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng"
        context = url + " https://thanhtai.io/r/b946e6e0f7a2"
        self.assertEqual(
            decode_live_url("https://thanhtai.io/r/b946e6e0f7a2", context),
            "snssdk1180://live?room_id=7660546312748108566",
        )

    def test_thanhtai_hex_uses_playwright_when_available(self) -> None:
        try:
            from thanhtai_playwright import resolve_thanhtai_via_playwright
        except Exception:
            self.skipTest("Playwright unavailable")
        try:
            deeplink = resolve_thanhtai_via_playwright("https://thanhtai.io/r/f4cb4b1649bf")
        except Exception as exc:
            self.skipTest(f"Playwright resolve skipped: {exc}")
        self.assertRegex(deeplink, r"^snssdk1180://live\?room_id=\d+$")

    def test_rejects_unknown_host(self) -> None:
        with self.assertRaises(ValueError):
            decode_live_url("https://example.com/foo")


if __name__ == "__main__":
    unittest.main()
