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

    def test_rejects_unknown_host(self) -> None:
        with self.assertRaises(ValueError):
            decode_live_url("https://example.com/foo")


if __name__ == "__main__":
    unittest.main()
