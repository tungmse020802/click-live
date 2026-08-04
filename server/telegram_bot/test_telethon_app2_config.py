"""Telethon app-2 reader config flags."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from config import load_telegram_client_config


class TelethonApp2ConfigTests(unittest.TestCase):
    def test_app2_env_targets_only(self) -> None:
        env = {
            "TELEGRAM_API_ID": "1",
            "TELEGRAM_API_HASH": "hash",
            "TELEGRAM_CLIENT_READER_ID": "app2",
            "TELEGRAM_CLIENT_USE_ENV_TARGETS": "true",
            "TELEGRAM_CLIENT_TARGETS": "G1|#-1001",
            "TELEGRAM_CLIENT_SESSION": "data/telegram_client_app2.session",
        }
        with patch.dict(os.environ, env, clear=False):
            cfg = load_telegram_client_config()
        self.assertEqual(cfg.reader_id, "app2")
        self.assertTrue(cfg.use_env_targets_only)
        self.assertEqual(len(cfg.targets), 1)
        self.assertEqual(cfg.targets[0].room_key, "-1001")


if __name__ == "__main__":
    unittest.main()
