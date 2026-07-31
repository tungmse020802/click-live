import unittest

from deeplink_resolve import (
    build_thanhtai_countdown_url,
    decode_live_url,
    enrich_payload_with_deeplink,
    extract_countdown_url,
    find_countdown_url_for_open,
    find_first_countdown_url,
    is_convertible_url,
    replace_urls_in_html,
    replace_urls_in_text,
    resolve_countdown_open_url,
    resolve_link_for_open,
    resolve_live_url,
)
from desktop_relay import normalize_open_url


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
        open_href = "http://127.0.0.1:8792/open/live?room_id=7660479963724434197"
        self.assertEqual(
            converted,
            f'Live <a href="{open_href}">{DEEPLINK}</a>',
        )

    def test_deeplink_open_href(self) -> None:
        from deeplink_resolve import deeplink_open_href

        self.assertEqual(
            deeplink_open_href(DEEPLINK),
            "http://127.0.0.1:8792/open/live?room_id=7660479963724434197",
        )

    def test_replace_urls_in_html(self) -> None:
        html_text = (
            f'<a href="{JUNB}"><strong>120</strong>/<strong>80</strong></a> '
            f'<a href="{JUNB}">{JUNB}</a>'
        )
        converted, count = replace_urls_in_html(html_text)
        self.assertGreaterEqual(count, 1)
        open_href = "http://127.0.0.1:8792/open/live?room_id=7660479963724434197"
        self.assertIn(f'<a href="{open_href}">{DEEPLINK}</a>', converted)
        self.assertIn(f'<a href="{open_href}"><strong>120</strong>/<strong>80</strong></a>', converted)

    def test_thanhtai_hex_uses_countdown_not_offline_decode(self) -> None:
        from unittest.mock import patch

        from deeplink_resolve import resolve_deeplink_from_text

        html = (
            "https://thanhtai.io/r/b946e6e0f7a2 "
            "https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng"
        )
        with patch("deeplink_resolve.resolve_via_deeplink_api", return_value=None):
            deeplink = resolve_deeplink_from_text(html)
        self.assertEqual(deeplink, "snssdk1180://live?room_id=7660546312748108566")
        self.assertNotEqual(deeplink, "snssdk1180://live?room_id=6837627643505146521")

    def test_thanhtai_hex_referral_not_convertible_alone(self) -> None:
        self.assertFalse(is_convertible_url("https://thanhtai.io/r/525ddbd53026"))
        self.assertFalse(is_convertible_url("https://thanhtai.io/r/b946e6e0f7a2"))

    def test_enrich_thanhtai_message_with_countdown(self) -> None:
        from unittest.mock import patch

        text = "live https://thanhtai.io/r/b946e6e0f7a2"
        html = '<a href="https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng">box</a>'
        with patch("deeplink_resolve.resolve_via_deeplink_api") as api_mock:
            api_mock.return_value = "snssdk1180://live?room_id=7660546312748108566"
            payload = enrich_payload_with_deeplink(text, {"telegram_html": html})
        self.assertEqual(payload["deeplink"], "snssdk1180://live?room_id=7660546312748108566")
        self.assertEqual(payload.get("source_url"), "https://thanhtai.io/r/b946e6e0f7a2")

    def test_build_thanhtai_countdown_url(self) -> None:
        self.assertEqual(
            build_thanhtai_countdown_url("7660546312748108566"),
            "https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng",
        )

    def test_resolve_link_for_open_countdown_passthrough(self) -> None:
        url = "https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng"
        result = resolve_link_for_open(url)
        self.assertTrue(result["ok"])
        self.assertEqual(result["countdown_url"], url)
        self.assertEqual(result["room_id"], "7660546312748108566")

    def test_resolve_link_for_open_offline_junb(self) -> None:
        result = resolve_link_for_open(JUNB)
        self.assertTrue(result["ok"])
        self.assertEqual(result["deeplink"], DEEPLINK)
        self.assertIn("thanhtai.io/countdow", result["countdown_url"])

    def test_find_junb_box_countdown_from_html(self) -> None:
        url = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiMXJhbSpvNjkiLCJjb2lucyI6NTAsImNhbl9vcGVuIjoyNX0=&t=abc&bt=1"
        )
        html = f'<a href="{url}"><strong>50</strong>/<strong>25</strong></a>'
        self.assertEqual(find_first_countdown_url(html), url)
        resolved = resolve_countdown_open_url(html, room_id="7660546312748108566")
        self.assertEqual(resolved, url)
        self.assertFalse(is_convertible_url(url))

    def test_resolve_link_for_open_junb_box_countdown(self) -> None:
        url = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiMXJhbSpvNjkiLCJjb2lucyI6NTAsImNhbl9vcGVuIjoyNX0="
        )
        html = f'<a href="{url}">50/25</a>'
        result = resolve_link_for_open(url, html)
        self.assertTrue(result["ok"])
        self.assertEqual(result["countdown_url"], url)
        self.assertEqual(result["open_url"], url)

    def test_resolve_link_for_open_prefers_thanhtai_in_message(self) -> None:
        tt = "https://thanhtai.io/countdow?data=NzY2MDU0NjMxMjc0ODEwODU2Ng"
        html = f'<a href="{tt}">50/25</a> https://thanhtai.io/r/b946e6e0f7a2'
        result = resolve_link_for_open("https://thanhtai.io/r/b946e6e0f7a2", html)
        self.assertTrue(result["ok"])
        self.assertEqual(result["countdown_url"], tt)

    def test_extract_countdown_prefers_50_25_anchor_over_stale_plain_url(self) -> None:
        correct = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiZGYqaC4uMSIsInJvb20iOiI3NjY4MzM4OTQwNDAxMDExNDc2IiwidHlwZSI6IkJBRyJ9"
            "&t=1fa7aef9d0082460d303df217895b6ad&bt=undefined"
        )
        stale = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoianVsKmFoYW5POTAxIiwicm9vbSI6Ijc2NjgzNTgwNzAxOTk3NDkzOTMiLCJ0eXBlIjoiQk9YJ9"
            "&t=2a2053e39f5cfd0e73a20a137b3ac0fc&bt=1"
        )
        html = f'<a href="{correct}"><strong>50</strong>/<strong>25</strong></a>'
        payload = {
            "telegram_html": html,
            "source_url": stale,
            "room_id": "7668358070199749393",
            "deeplink": "snssdk1180://live?room_id=7668358070199749393",
        }
        self.assertEqual(extract_countdown_url(stale + "\n" + html, payload), correct)
        self.assertEqual(
            resolve_countdown_open_url(stale + "\n" + html, room_id="7668358070199749393"),
            correct,
        )

    def test_extract_countdown_unescapes_amp_in_href(self) -> None:
        url = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiZGYqaC4uMSI&amp;m=%7B%22hot_box_str%22%3A%22x%22%7D"
            "&amp;t=abc&amp;bt=undefined"
        )
        expected = url.replace("&amp;", "&")
        html = f'<a href="{url}"><strong>50</strong>/<strong>25</strong></a>'
        self.assertEqual(extract_countdown_url("", {"telegram_html": html}), expected)

    def test_extract_countdown_matches_display_html(self) -> None:
        correct = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoibSpvLi5PMDguMSIsInJvb20iOiI3NjY4MzUyODg5ODkwMzYwMDg1IiwidHlwZSI6IkJPWCJ9"
            "&t=94fb8b27455c497c37aa31e8d6a7f00f&bt=4"
        )
        stale = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiYnV4YXIqOTk2Iiwicm9vbSI6Ijc2NjgzNTY0NzExMDAzMjg3MjYiIiwidHlwZSI6IkJPWCJ9"
            "&t=37e311c079f89edaead9c5a1e2f6b47e&bt=4"
        )
        html = f'<a href="{correct}"><strong>50</strong>/<strong>30</strong></a>'
        from message_format import queue_display_from_payload

        display_html, _ = queue_display_from_payload("", {"telegram_html": html})
        payload = {
            "telegram_html": html,
            "source_url": stale,
            "room_id": "7668356471100328726",
        }
        self.assertEqual(find_countdown_url_for_open(display_html), correct)
        self.assertEqual(extract_countdown_url(stale, payload), correct)

    def test_normalize_open_url_junb_r_param(self) -> None:
        url = (
            "https://i.junb.io.vn/box-countdown/index4.html?"
            "r=eyJ1c2VyIjoiZGYqaC4uMSI&amp;m=x&amp;t=abc&amp;bt=undefined"
        )
        key = normalize_open_url(url)
        self.assertEqual(
            key,
            "https://i.junb.io.vn/box-countdown/index4.html?r=eyJ1c2VyIjoiZGYqaC4uMSI",
        )
        self.assertNotEqual(
            normalize_open_url(
                "https://i.junb.io.vn/box-countdown/index4.html?r=eyJ1c2VyIjoianVsKmFoYW5POTAx"
            ),
            key,
        )


if __name__ == "__main__":
    unittest.main()
