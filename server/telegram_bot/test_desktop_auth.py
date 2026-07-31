"""Per-user desktop pull tokens and relay isolation."""

from __future__ import annotations

import unittest

from desktop_auth import (
    DEFAULT_QUEUE_PASSWORD,
    desktop_pull_token_for_user,
    format_queue_users,
    parse_queue_users,
    resolve_username_from_desktop_token,
    list_queue_usernames,
    seed_queue_users,
    verify_queue_user,
)
from desktop_relay import enqueue_open, pull_pending
from config import QueueUiConfig


def _config(*, users=None, secret="test-secret", legacy_user="admin"):
    user_map = dict(users or [("admin1", "pass1"), ("admin2", "pass2")])
    return QueueUiConfig(
        log_level="ERROR",
        db_path="data/chatbot.sqlite3",
        host="127.0.0.1",
        port=8787,
        limit=100,
        refresh_seconds=3,
        queue_ttl_seconds=1800,
        queue_lease_seconds=90,
        queue_retry_delay_seconds=2,
        filter_config_path="data/message_filters.json",
        auth_enabled=True,
        auth_username=legacy_user,
        auth_password="legacy-pass",
        auth_secret=secret,
        queue_users=tuple(user_map.items()),
        desktop_dedup_seconds=90,
    )


class DesktopAuthTests(unittest.TestCase):
    def test_parse_queue_users(self):
        users = parse_queue_users("admin1:pass1, admin2:pass2")
        self.assertEqual(users, {"admin1": "pass1", "admin2": "pass2"})

    def test_seed_queue_users(self):
        users = seed_queue_users(10)
        self.assertEqual(len(users), 10)
        self.assertEqual(users["admin1"], DEFAULT_QUEUE_PASSWORD)
        self.assertEqual(users["admin10"], DEFAULT_QUEUE_PASSWORD)
        self.assertEqual(
            format_queue_users(users),
            ",".join(f"admin{i}:{DEFAULT_QUEUE_PASSWORD}" for i in range(1, 11)),
        )

    def test_list_queue_usernames(self):
        users = seed_queue_users(3)
        self.assertEqual(list_queue_usernames(users), ["admin1", "admin2", "admin3"])

    def test_verify_queue_user(self):
        users = {"admin1": "pass1"}
        self.assertTrue(verify_queue_user("admin1", "pass1", users))
        self.assertFalse(verify_queue_user("admin1", "wrong", users))
        self.assertFalse(verify_queue_user("admin2", "pass1", users))

    def test_token_per_user(self):
        secret = "abc"
        t1 = desktop_pull_token_for_user("admin1", secret)
        t2 = desktop_pull_token_for_user("admin2", secret)
        self.assertNotEqual(t1, t2)
        self.assertEqual(
            resolve_username_from_desktop_token(t1, users={"admin1": "x", "admin2": "y"}, secret=secret),
            "admin1",
        )

    def test_relay_user_isolation(self):
        import desktop_relay as relay

        relay._pending.clear()
        relay._opened_urls.clear()
        relay._last_desktop_ping.clear()

        cfg = _config()
        enqueue_open("https://example.com/a", job_id=1, queue_user="admin1")
        enqueue_open("https://example.com/b", job_id=2, queue_user="admin2")

        token1 = desktop_pull_token_for_user("admin1", cfg.auth_secret)
        token2 = desktop_pull_token_for_user("admin2", cfg.auth_secret)

        pull1 = pull_pending(token1, cfg)
        self.assertTrue(pull1["ok"])
        self.assertEqual(pull1["queue_user"], "admin1")
        self.assertEqual(len(pull1["opens"]), 1)
        self.assertIn("example.com/a", pull1["opens"][0]["url"])

        pull2 = pull_pending(token2, cfg)
        self.assertEqual(pull2["queue_user"], "admin2")
        self.assertEqual(len(pull2["opens"]), 1)
        self.assertIn("example.com/b", pull2["opens"][0]["url"])

        empty = pull_pending(token1, cfg)
        self.assertEqual(empty["opens"], [])


if __name__ == "__main__":
    unittest.main()
