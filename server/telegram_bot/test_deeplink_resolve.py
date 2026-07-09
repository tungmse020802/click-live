import unittest

from deeplink_resolve import (
    decode_live_url,
    enrich_payload_with_deeplink,
    is_convertible_url,
    replace_urls_in_html,
    replace_urls_in_text,
    resolve_live_url,
)


JUNB = "https://i.junb.io.vn/i/?b7YVmORSncRD4"
THANHTAI = "https://thanhtai.io/r/b7YVmORSncRD4"
DEEPLINK = "snssdk1180://live?room_id=7660479963724434197"


class DeeplinkResolveTest(unittest.TestCase):
    def test_is_convertible_url(self) -> None:
        self.assertTrue(is_convertible_url(JUNB))
        self.assertTrue(is_convertible_url(THANHTAI))
        self.assertFalse(is_convertible_url("https://tiktok.com/@user/live"))
        self.assertFalse(is_convertible_url(DEEPLINK))
        self.assertFalse(
            is_convertible_url("https://i.junb.io.vn/bot-config?access_token=abc")
        )

    def test_decode_live_url(self) -> None:
        self.assertEqual(decode_live_url(JUNB), DEEPLINK)
        self.assertEqual(decode_live_url(THANHTAI), DEEPLINK)

    def test_resolve_live_url_keeps_unknown(self) -> None:
        url = "https://example.com/live"
        self.assertEqual(resolve_live_url(url), url)

    def test_replace_urls_in_text(self) -> None:
        text = f"Live here {THANHTAI} now"
        converted, count = replace_urls_in_text(text)
        self.assertEqual(count, 1)
        self.assertIn(DEEPLINK, converted)
        self.assertNotIn("thanhtai.io", converted)

    def test_replace_urls_as_deeplink_hyperlinks(self) -> None:
        from deeplink_resolve import replace_urls_as_deeplink_hyperlinks

        text = f"Live {THANHTAI}"
        converted, count = replace_urls_as_deeplink_hyperlinks(text)
        self.assertEqual(count, 1)
        open_href = f"http://103.38.237.7:8792/open/live?room_id=7660479963724434197"
        self.assertEqual(
            converted,
            f'Live <a href="{open_href}">{DEEPLINK}</a>',
        )

    def test_deeplink_open_href(self) -> None:
        from deeplink_resolve import deeplink_open_href

        self.assertEqual(
            deeplink_open_href(DEEPLINK),
            "http://103.38.237.7:8792/open/live?room_id=7660479963724434197",
        )

    def test_replace_urls_in_html(self) -> None:
        html_text = (
            f'<a href="{JUNB}"><strong>120</strong>/<strong>80</strong></a> '
            f'<a href="{JUNB}">{JUNB}</a>'
        )
        converted, count = replace_urls_in_html(html_text)
        self.assertGreaterEqual(count, 1)
        open_href = "http://103.38.237.7:8792/open/live?room_id=7660479963724434197"
        self.assertIn(f'<a href="{open_href}">{DEEPLINK}</a>', converted)
        self.assertIn(f'<a href="{open_href}"><strong>120</strong>/<strong>80</strong></a>', converted)

    def test_enrich_payload_with_deeplink(self) -> None:
        payload = enrich_payload_with_deeplink(f"box {JUNB}", {})
        self.assertEqual(payload["deeplink"], DEEPLINK)
        self.assertEqual(payload["source_url"], JUNB)


if __name__ == "__main__":
    unittest.main()
