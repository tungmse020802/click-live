import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class QueueJob:
    id: int
    message_id: int
    room_id: int
    priority: int
    attempts: int
    max_attempts: int
    payload: Dict[str, Any]
    message_text: str
    room_chat_id: str
    platform_user_id: Optional[str]
    username: Optional[str]
    locked_until: float


@dataclass(frozen=True)
class HistoryMessage:
    id: int
    direction: str
    text: str
    created_at: float
    platform_user_id: Optional[str]
    username: Optional[str]


class ChatDatabase:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS chat_rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    chat_type TEXT,
                    title TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(platform, chat_id)
                );

                CREATE TABLE IF NOT EXISTS chat_users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    platform TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    username TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(platform, user_id)
                );

                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id INTEGER NOT NULL,
                    user_id INTEGER,
                    platform_message_id TEXT,
                    direction TEXT NOT NULL CHECK(direction IN ('incoming', 'outgoing', 'system')),
                    text TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    FOREIGN KEY(room_id) REFERENCES chat_rooms(id),
                    FOREIGN KEY(user_id) REFERENCES chat_users(id)
                );

                CREATE INDEX IF NOT EXISTS idx_chat_messages_room_created
                    ON chat_messages(room_id, created_at);

                CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_messages_unique_platform_message
                    ON chat_messages(room_id, direction, platform_message_id)
                    WHERE platform_message_id IS NOT NULL;

                CREATE TABLE IF NOT EXISTS message_queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    message_id INTEGER NOT NULL,
                    room_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'processing', 'done', 'failed', 'dead')),
                    priority INTEGER NOT NULL DEFAULT 100,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 5,
                    locked_by TEXT,
                    locked_until REAL,
                    available_at REAL NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL,
                    last_error TEXT,
                    FOREIGN KEY(message_id) REFERENCES chat_messages(id),
                    FOREIGN KEY(room_id) REFERENCES chat_rooms(id)
                );

                CREATE INDEX IF NOT EXISTS idx_message_queue_claim
                    ON message_queue(status, available_at, priority, created_at);

                CREATE INDEX IF NOT EXISTS idx_message_queue_locked
                    ON message_queue(status, locked_until);

                CREATE INDEX IF NOT EXISTS idx_message_queue_created
                    ON message_queue(created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_message_queue_status_created
                    ON message_queue(status, created_at DESC);

                CREATE INDEX IF NOT EXISTS idx_message_queue_message_id
                    ON message_queue(message_id);

                CREATE TABLE IF NOT EXISTS broadcast_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(chat_id)
                );

                CREATE INDEX IF NOT EXISTS idx_broadcast_groups_enabled
                    ON broadcast_groups(enabled, name);

                CREATE TABLE IF NOT EXISTS watch_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    chat_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(chat_id)
                );

                CREATE INDEX IF NOT EXISTS idx_watch_groups_enabled
                    ON watch_groups(enabled, name);
                """
            )
            self._migrate_broadcast_groups(conn)
            self._migrate_bot_tables(conn)
            self._migrate_watch_groups_reader_id(conn)
            self._migrate_reader_group_filters(conn)

    def _migrate_watch_groups_reader_id(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(watch_groups)").fetchall()
        }
        if "reader_id" in columns:
            return

        conn.executescript(
            """
            CREATE TABLE watch_groups_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reader_id TEXT NOT NULL DEFAULT 'app1',
                name TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(reader_id, chat_id)
            );

            INSERT INTO watch_groups_new(
                id, reader_id, name, chat_id, enabled, created_at, updated_at
            )
            SELECT id, 'app1', name, chat_id, enabled, created_at, updated_at
            FROM watch_groups;

            DROP TABLE watch_groups;
            ALTER TABLE watch_groups_new RENAME TO watch_groups;

            CREATE INDEX IF NOT EXISTS idx_watch_groups_enabled
                ON watch_groups(enabled, reader_id, name);
            """
        )

    def _migrate_reader_group_filters(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reader_group_filters (
                reader_id TEXT NOT NULL,
                chat_id TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'inherit',
                filters_json TEXT NOT NULL DEFAULT '[]',
                reject_json TEXT NOT NULL DEFAULT '[]',
                updated_at REAL NOT NULL,
                PRIMARY KEY (reader_id, chat_id)
            );

            CREATE INDEX IF NOT EXISTS idx_reader_group_filters_reader
                ON reader_group_filters(reader_id);
            """
        )

    def _migrate_bot_tables(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS broadcast_bots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                short_name TEXT NOT NULL UNIQUE,
                token TEXT NOT NULL DEFAULT '',
                telegram_username TEXT,
                telegram_display_name TEXT,
                enabled INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_broadcast_bots_enabled
                ON broadcast_bots(enabled, sort_order, short_name);

            CREATE TABLE IF NOT EXISTS watch_group_bots (
                watch_chat_id TEXT NOT NULL,
                bot_id INTEGER NOT NULL,
                PRIMARY KEY (watch_chat_id, bot_id),
                FOREIGN KEY (bot_id) REFERENCES broadcast_bots(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_watch_group_bots_chat
                ON watch_group_bots(watch_chat_id);
            """
        )

    def ensure_broadcast_bot_slots(self, slot_count: int = 24) -> None:
        now = _now()
        with self._connect() as conn:
            for index in range(1, slot_count + 1):
                short_name = f"b{index:02d}"
                conn.execute(
                    """
                    INSERT OR IGNORE INTO broadcast_bots(
                        short_name, token, enabled, sort_order, created_at, updated_at
                    )
                    VALUES (?, '', 1, ?, ?, ?)
                    """,
                    (short_name, index, now, now),
                )

    def delete_broadcast_bots_without_tokens(self) -> int:
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            cursor = conn.execute(
                """
                DELETE FROM broadcast_bots
                WHERE trim(COALESCE(token, '')) = ''
                """
            )
            return int(cursor.rowcount or 0)

    def seed_broadcast_bots_from_tokens(self, tokens: List[str]) -> int:
        normalized_tokens = [(token or "").strip() for token in tokens if (token or "").strip()]
        if not normalized_tokens:
            self.delete_broadcast_bots_without_tokens()
            return 0

        self.ensure_broadcast_bot_slots(len(normalized_tokens))
        now = _now()
        bots = self.list_broadcast_bots(include_disabled=True)
        imported = 0

        for index, slot in enumerate(bots):
            token = normalized_tokens[index] if index < len(normalized_tokens) else ""
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE broadcast_bots
                    SET token = ?, enabled = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (token, 1 if token else 0, now, int(slot["id"])),
                )
            if token:
                imported += 1

        self.delete_broadcast_bots_without_tokens()
        return imported

    def list_broadcast_bots(self, *, include_disabled: bool = True) -> List[Dict[str, Any]]:
        query = """
            SELECT id, short_name, token, telegram_username, telegram_display_name,
                   enabled, sort_order, created_at, updated_at
            FROM broadcast_bots
        """
        if not include_disabled:
            query += " WHERE enabled = 1"
        query += " ORDER BY sort_order ASC, short_name ASC"
        with self._connect() as conn:
            rows = conn.execute(query).fetchall()
        return [_row_to_broadcast_bot(row) for row in rows]

    def replace_broadcast_bots(self, bots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [
            bot
            for bot in (_normalize_broadcast_bot(raw, now) for raw in bots)
            if bot["token"]
        ]
        if normalized:
            self.ensure_broadcast_bot_slots(len(normalized))
        with self._connect() as conn:
            for bot in normalized:
                conn.execute(
                    """
                    UPDATE broadcast_bots
                    SET token = ?, telegram_username = ?, telegram_display_name = ?,
                        enabled = ?, sort_order = ?, updated_at = ?
                    WHERE short_name = ?
                    """,
                    (
                        bot["token"],
                        bot.get("telegram_username"),
                        bot.get("telegram_display_name"),
                        1 if bot.get("enabled", True) else 0,
                        bot["sort_order"],
                        now,
                        bot["short_name"],
                    ),
                )
        self.delete_broadcast_bots_without_tokens()
        return self.list_broadcast_bots(include_disabled=True)

    def list_enabled_broadcast_bot_tokens(self) -> List[Dict[str, Any]]:
        return [
            bot
            for bot in self.list_broadcast_bots(include_disabled=False)
            if (bot.get("token") or "").strip()
        ]

    def list_watch_group_bot_map(self) -> Dict[str, List[int]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT watch_chat_id, bot_id
                FROM watch_group_bots
                ORDER BY watch_chat_id ASC, bot_id ASC
                """
            ).fetchall()
        result: Dict[str, List[int]] = {}
        for row in rows:
            chat_id = str(row["watch_chat_id"])
            result.setdefault(chat_id, []).append(int(row["bot_id"]))
        return result

    def set_watch_group_bots(self, watch_chat_id: str, bot_ids: List[int]) -> None:
        from config import normalize_client_chat_ref

        chat_id = normalize_client_chat_ref(str(watch_chat_id or "").strip())
        if not chat_id:
            return
        unique_ids = []
        for bot_id in bot_ids or []:
            try:
                value = int(bot_id)
            except (TypeError, ValueError):
                continue
            if value not in unique_ids:
                unique_ids.append(value)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM watch_group_bots WHERE watch_chat_id = ?",
                (chat_id,),
            )
            for bot_id in unique_ids:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO watch_group_bots(watch_chat_id, bot_id)
                    VALUES (?, ?)
                    """,
                    (chat_id, bot_id),
                )

    def get_bot_ids_for_watch_chat_id(self, watch_chat_id: str) -> List[int]:
        from config import normalize_client_chat_ref

        chat_id = normalize_client_chat_ref(str(watch_chat_id or "").strip())
        if not chat_id:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT bot_id
                FROM watch_group_bots
                WHERE watch_chat_id = ?
                ORDER BY bot_id ASC
                """,
                (chat_id,),
            ).fetchall()
        return [int(row["bot_id"]) for row in rows]

    def list_enabled_bots_for_watch_chat_id(self, watch_chat_id: str) -> List[Dict[str, Any]]:
        bot_ids = self.get_bot_ids_for_watch_chat_id(watch_chat_id)
        if not bot_ids:
            return []
        enabled = {
            int(bot["id"]): bot
            for bot in self.list_broadcast_bots(include_disabled=False)
            if (bot.get("token") or "").strip()
        }
        return [enabled[bot_id] for bot_id in bot_ids if bot_id in enabled]

    def update_broadcast_bot_profile(
        self,
        bot_id: int,
        *,
        telegram_username: Optional[str],
        telegram_display_name: Optional[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE broadcast_bots
                SET telegram_username = ?, telegram_display_name = ?, updated_at = ?
                WHERE id = ?
                """,
                (telegram_username, telegram_display_name, _now(), bot_id),
            )

    def _migrate_broadcast_groups(self, conn: sqlite3.Connection) -> None:
        columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(broadcast_groups)").fetchall()
        }
        if "approved" not in columns:
            conn.execute(
                """
                ALTER TABLE broadcast_groups
                ADD COLUMN approved INTEGER NOT NULL DEFAULT 0
                """
            )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_broadcast_groups_approved
                ON broadcast_groups(approved, enabled, name)
            """
        )

    def upsert_chat_room(
        self,
        platform: str,
        chat_id: str,
        chat_type: Optional[str],
        title: Optional[str],
    ) -> int:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_rooms(platform, chat_id, chat_type, title, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, chat_id) DO UPDATE SET
                    chat_type = excluded.chat_type,
                    title = COALESCE(excluded.title, chat_rooms.title),
                    updated_at = excluded.updated_at
                """,
                (platform, chat_id, chat_type, title, now, now),
            )
            row = conn.execute(
                "SELECT id FROM chat_rooms WHERE platform = ? AND chat_id = ?",
                (platform, chat_id),
            ).fetchone()
            return int(row["id"])

    def upsert_chat_user(
        self,
        platform: str,
        user_id: str,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
    ) -> int:
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO chat_users(
                    platform, user_id, username, first_name, last_name, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(platform, user_id) DO UPDATE SET
                    username = excluded.username,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    updated_at = excluded.updated_at
                """,
                (platform, user_id, username, first_name, last_name, now, now),
            )
            row = conn.execute(
                "SELECT id FROM chat_users WHERE platform = ? AND user_id = ?",
                (platform, user_id),
            ).fetchone()
            return int(row["id"])

    def insert_chat_message(
        self,
        room_id: int,
        user_id: Optional[int],
        platform_message_id: Optional[str],
        direction: str,
        text: str,
    ) -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO chat_messages(
                    room_id, user_id, platform_message_id, direction, text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (room_id, user_id, platform_message_id, direction, text, now),
            )
            return int(cursor.lastrowid)

    def insert_chat_message_if_new(
        self,
        room_id: int,
        user_id: Optional[int],
        platform_message_id: str,
        direction: str,
        text: str,
        created_at: Optional[float] = None,
    ) -> Optional[int]:
        now = float(created_at) if created_at is not None else _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO chat_messages(
                    room_id, user_id, platform_message_id, direction, text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (room_id, user_id, platform_message_id, direction, text, now),
            )
            if cursor.rowcount == 0:
                return None
            return int(cursor.lastrowid)

    def insert_message_and_enqueue(
        self,
        *,
        room_id: int,
        user_id: Optional[int],
        platform_message_id: str,
        direction: str,
        text: str,
        created_at: Optional[float],
        priority: int,
        payload: Dict[str, Any],
        max_attempts: int,
    ) -> Tuple[Optional[int], Optional[int]]:
        """Insert chat message + queue row in one transaction (avoids FK race)."""
        now = float(created_at) if created_at is not None else _now()
        enqueue_at = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO chat_messages(
                    room_id, user_id, platform_message_id, direction, text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (room_id, user_id, platform_message_id, direction, text, now),
            )
            if cursor.rowcount == 0:
                return None, None
            message_id = int(cursor.lastrowid)
            queue_cursor = conn.execute(
                """
                INSERT INTO message_queue(
                    message_id, room_id, status, priority, payload_json,
                    attempts, max_attempts, available_at, created_at, updated_at
                )
                VALUES (?, ?, 'pending', ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    room_id,
                    priority,
                    json.dumps(payload, ensure_ascii=False),
                    max_attempts,
                    enqueue_at,
                    enqueue_at,
                    enqueue_at,
                ),
            )
            return message_id, int(queue_cursor.lastrowid)

    def max_telegram_message_id_for_room(self, room_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(
                    CAST(SUBSTR(platform_message_id, INSTR(platform_message_id, ':') + 1) AS INTEGER)
                ) AS max_id
                FROM chat_messages
                WHERE room_id = ?
                    AND platform_message_id IS NOT NULL
                    AND INSTR(platform_message_id, ':') > 0
                """,
                (room_id,),
            ).fetchone()
        if row is None or row["max_id"] is None:
            return 0
        return int(row["max_id"])

    def list_broadcast_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, approved, created_at, updated_at
                FROM broadcast_groups
                ORDER BY approved DESC, name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_broadcast_group(row) for row in rows]

    def list_pending_broadcast_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, approved, created_at, updated_at
                FROM broadcast_groups
                WHERE approved = 0
                ORDER BY updated_at DESC, name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_broadcast_group(row) for row in rows]

    def list_approved_broadcast_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, approved, created_at, updated_at
                FROM broadcast_groups
                WHERE approved = 1
                ORDER BY name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_broadcast_group(row) for row in rows]

    def list_enabled_broadcast_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, approved, created_at, updated_at
                FROM broadcast_groups
                WHERE approved = 1 AND enabled = 1
                ORDER BY name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_broadcast_group(row) for row in rows]

    def upsert_pending_broadcast_group(self, chat_id: str, name: str) -> bool:
        now = _now()
        chat_id = str(chat_id).strip()
        name = str(name or chat_id).strip() or chat_id
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, approved, name FROM broadcast_groups WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO broadcast_groups(
                        name, chat_id, enabled, approved, created_at, updated_at
                    )
                    VALUES (?, ?, 1, 0, ?, ?)
                    """,
                    (name, chat_id, now, now),
                )
                return True

            new_name = name if name != chat_id or row["name"] == chat_id else row["name"]
            conn.execute(
                """
                UPDATE broadcast_groups
                SET name = ?, updated_at = ?
                WHERE chat_id = ?
                """,
                (new_name, now, chat_id),
            )
            return False

    def approve_broadcast_group(self, group_id: int, name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT id, name FROM broadcast_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            if row is None:
                return None
            final_name = str(name or row["name"]).strip() or row["name"]
            conn.execute(
                """
                UPDATE broadcast_groups
                SET approved = 1, enabled = 1, name = ?, updated_at = ?
                WHERE id = ?
                """,
                (final_name, now, group_id),
            )
            updated = conn.execute(
                """
                SELECT id, name, chat_id, enabled, approved, created_at, updated_at
                FROM broadcast_groups
                WHERE id = ?
                """,
                (group_id,),
            ).fetchone()
        if updated is None:
            return None
        return _row_to_broadcast_group(updated)

    def replace_approved_broadcast_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [_normalize_broadcast_group({**raw, "approved": True}, now) for raw in groups]
        with self._connect() as conn:
            conn.execute("DELETE FROM broadcast_groups WHERE approved = 1")
            for group in normalized:
                conn.execute(
                    """
                    INSERT INTO broadcast_groups(
                        name, chat_id, enabled, approved, created_at, updated_at
                    )
                    VALUES (?, ?, ?, 1, ?, ?)
                    """,
                    (
                        group["name"],
                        group["chat_id"],
                        1 if group.get("enabled", True) else 0,
                        group.get("created_at", now),
                        now,
                    ),
                )
        return self.list_broadcast_groups()

    def delete_broadcast_group(self, group_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM broadcast_groups WHERE id = ?",
                (group_id,),
            )
            return cursor.rowcount > 0

    def list_watch_groups(self, *, reader_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = """
            SELECT id, reader_id, name, chat_id, enabled, created_at, updated_at
            FROM watch_groups
        """
        params: tuple = ()
        if reader_id is not None:
            query += " WHERE reader_id = ?"
            params = (reader_id,)
        query += " ORDER BY reader_id ASC, name ASC, id ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        bot_map = self.list_watch_group_bot_map()
        filter_map = self.list_reader_group_filter_map()
        groups = [_row_to_watch_group(row) for row in rows]
        for group in groups:
            group["bot_ids"] = bot_map.get(group["chat_id"], [])
            group["filter"] = filter_map.get(
                (group["reader_id"], group["chat_id"]),
                _default_reader_group_filter(),
            )
        return groups

    def list_enabled_watch_groups(self, *, reader_id: str) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, reader_id, name, chat_id, enabled, created_at, updated_at
                FROM watch_groups
                WHERE enabled = 1 AND reader_id = ?
                ORDER BY name ASC, id ASC
                """,
                (reader_id,),
            ).fetchall()
        return [_row_to_watch_group(row) for row in rows]

    def replace_watch_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [_normalize_watch_group(raw, now) for raw in groups]
        bot_assignments = {
            (group["reader_id"], group["chat_id"]): [
                int(bot_id)
                for bot_id in (raw.get("bot_ids") or [])
                if str(bot_id).strip().isdigit()
            ]
            for raw, group in zip(groups, normalized)
        }
        with self._connect() as conn:
            conn.execute("DELETE FROM watch_groups")
            for group in normalized:
                conn.execute(
                    """
                    INSERT INTO watch_groups(
                        reader_id, name, chat_id, enabled, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group["reader_id"],
                        group["name"],
                        group["chat_id"],
                        1 if group.get("enabled", True) else 0,
                        group.get("created_at", now),
                        now,
                    ),
                )
        for (_, chat_id), bot_ids in bot_assignments.items():
            self.set_watch_group_bots(chat_id, bot_ids)
        return self.list_watch_groups()

    def replace_watch_groups_for_reader(
        self,
        reader_id: str,
        groups: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [
            _normalize_watch_group({**raw, "reader_id": reader_id}, now) for raw in groups
        ]
        bot_assignments = {
            group["chat_id"]: [
                int(bot_id)
                for bot_id in (raw.get("bot_ids") or [])
                if str(bot_id).strip().isdigit()
            ]
            for raw, group in zip(groups, normalized)
        }
        with self._connect() as conn:
            conn.execute("DELETE FROM watch_groups WHERE reader_id = ?", (reader_id,))
            for group in normalized:
                conn.execute(
                    """
                    INSERT INTO watch_groups(
                        reader_id, name, chat_id, enabled, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        reader_id,
                        group["name"],
                        group["chat_id"],
                        1 if group.get("enabled", True) else 0,
                        group.get("created_at", now),
                        now,
                    ),
                )
        for chat_id, bot_ids in bot_assignments.items():
            self.set_watch_group_bots(chat_id, bot_ids)
        return self.list_watch_groups(reader_id=reader_id)

    def sync_room_titles_from_watch_groups(self) -> int:
        from config import _telegram_client_entity_ref, normalize_client_chat_ref

        updated = 0
        now = _now()
        for group in self.list_watch_groups():
            if not group.get("enabled", True):
                continue
            name = str(group.get("name") or "").strip()
            if not name or name.lstrip("-").isdigit():
                continue
            chat_ref = normalize_client_chat_ref(str(group.get("chat_id") or ""))
            aliases = {chat_ref, _telegram_client_entity_ref(chat_ref)}
            if chat_ref.startswith("-100") and len(chat_ref) > 4:
                aliases.add("-" + chat_ref[4:])
            elif chat_ref.startswith("-") and not chat_ref.startswith("-100"):
                aliases.add("-100" + chat_ref[1:])
            aliases.discard("")
            with self._connect() as conn:
                for alias in aliases:
                    cursor = conn.execute(
                        """
                        UPDATE chat_rooms
                        SET title = ?, updated_at = ?
                        WHERE chat_id = ?
                          AND (title IS NULL OR title = '' OR title = chat_id OR title GLOB '-[0-9]*')
                        """,
                        (name, now, alias),
                    )
                    updated += int(cursor.rowcount or 0)
        return updated

    def list_reader_group_filter_map(self) -> Dict[tuple, Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT reader_id, chat_id, mode, filters_json, reject_json, updated_at
                FROM reader_group_filters
                """
            ).fetchall()
        result: Dict[tuple, Dict[str, Any]] = {}
        for row in rows:
            key = (str(row["reader_id"]), str(row["chat_id"]))
            result[key] = _row_to_reader_group_filter(row)
        return result

    def get_reader_group_filter(
        self,
        reader_id: str,
        chat_id: str,
    ) -> Dict[str, Any]:
        from config import chat_id_aliases

        candidates = chat_id_aliases(chat_id) or [str(chat_id or "").strip()]
        with self._connect() as conn:
            for candidate in candidates:
                if not candidate:
                    continue
                row = conn.execute(
                    """
                    SELECT reader_id, chat_id, mode, filters_json, reject_json, updated_at
                    FROM reader_group_filters
                    WHERE reader_id = ? AND chat_id = ?
                    """,
                    (reader_id, candidate),
                ).fetchone()
                if row is not None:
                    return _row_to_reader_group_filter(row)
        return _default_reader_group_filter()

    def upsert_reader_group_filter(
        self,
        reader_id: str,
        chat_id: str,
        *,
        mode: str,
        filters: Optional[List[Dict[str, Any]]] = None,
        reject: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        mode = str(mode or "inherit").strip() or "inherit"
        if mode not in {"inherit", "custom", "pass_all", "block_all"}:
            raise ValueError(f"invalid reader group filter mode: {mode}")

        existing = self.get_reader_group_filter(reader_id, chat_id)
        filters_payload = filters if filters is not None else existing.get("filters", [])
        reject_payload = reject if reject is not None else existing.get("reject", [])
        now = _now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO reader_group_filters(
                    reader_id, chat_id, mode, filters_json, reject_json, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(reader_id, chat_id) DO UPDATE SET
                    mode = excluded.mode,
                    filters_json = excluded.filters_json,
                    reject_json = excluded.reject_json,
                    updated_at = excluded.updated_at
                """,
                (
                    reader_id,
                    chat_id,
                    mode,
                    json.dumps(filters_payload, ensure_ascii=False),
                    json.dumps(reject_payload, ensure_ascii=False),
                    now,
                ),
            )
        return self.get_reader_group_filter(reader_id, chat_id)

    def delete_reader_group_filter(self, reader_id: str, chat_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                """
                DELETE FROM reader_group_filters
                WHERE reader_id = ? AND chat_id = ?
                """,
                (reader_id, chat_id),
            )
            return cursor.rowcount > 0

    def delete_watch_group(self, group_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM watch_groups WHERE id = ?",
                (group_id,),
            )
            return cursor.rowcount > 0

    def seed_watch_groups_if_empty(self, groups: List[Dict[str, Any]]) -> int:
        if self.list_watch_groups():
            return 0
        if not groups:
            return 0
        self.replace_watch_groups(groups)
        return len(groups)

    def replace_broadcast_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [_normalize_broadcast_group(raw, now) for raw in groups]
        with self._connect() as conn:
            conn.execute("DELETE FROM broadcast_groups")
            for group in normalized:
                conn.execute(
                    """
                    INSERT INTO broadcast_groups(
                        name, chat_id, enabled, approved, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        group["name"],
                        group["chat_id"],
                        1 if group.get("enabled", True) else 0,
                        1 if group.get("approved", True) else 0,
                        group.get("created_at", now),
                        now,
                    ),
                )
        return self.list_broadcast_groups()

    def supersede_all_pending_for_room(self, room_id: int) -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    last_error = 'superseded by newer message',
                    completed_at = ?,
                    updated_at = ?
                WHERE status = 'pending'
                    AND room_id = ?
                """,
                (now, now, room_id),
            )
            return int(cursor.rowcount)

    def supersede_all_pending(self) -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    last_error = 'superseded by newer message',
                    completed_at = ?,
                    updated_at = ?
                WHERE status = 'pending'
                """,
                (now, now),
            )
            return int(cursor.rowcount)

    def enqueue_message(
        self,
        message_id: int,
        room_id: int,
        priority: int,
        payload: Dict[str, Any],
        max_attempts: int,
    ) -> int:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO message_queue(
                    message_id, room_id, status, priority, payload_json,
                    attempts, max_attempts, available_at, created_at, updated_at
                )
                VALUES (?, ?, 'pending', ?, ?, 0, ?, ?, ?, ?)
                """,
                (
                    message_id,
                    room_id,
                    priority,
                    json.dumps(payload, ensure_ascii=False),
                    max_attempts,
                    now,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid)

    def release_expired_jobs(self) -> int:
        now = _now()
        with self._connect() as conn:
            return self._release_expired_jobs(conn, now)

    def claim_next(self, consumer_id: str, lease_seconds: int) -> Optional[QueueJob]:
        now = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._release_expired_jobs(conn, now)

            row = conn.execute(
                """
                SELECT id
                FROM message_queue
                WHERE status = 'pending'
                    AND available_at <= ?
                ORDER BY priority DESC, created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.commit()
                return None

            job_id = int(row["id"])
            locked_until = now + lease_seconds
            conn.execute(
                """
                UPDATE message_queue
                SET status = 'processing',
                    locked_by = ?,
                    locked_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (consumer_id, locked_until, now, job_id),
            )

            job_row = self._fetch_job_row(conn, job_id)
            conn.commit()
            return _row_to_job(job_row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def claim_next_fair(self, consumer_id: str, lease_seconds: int) -> Optional[QueueJob]:
        """Claim newest pending job from a free room (fair across listening groups).

        Prefers rooms that do not already have a job in `processing`, so multiple
        workers can run one logical queue per watch room in parallel.
        """
        now = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._release_expired_jobs(conn, now)

            row = conn.execute(
                """
                SELECT q.id
                FROM message_queue q
                INNER JOIN (
                    SELECT room_id, MAX(created_at) AS room_latest
                    FROM message_queue
                    WHERE status = 'pending'
                        AND available_at <= ?
                    GROUP BY room_id
                ) rooms ON rooms.room_id = q.room_id
                WHERE q.status = 'pending'
                    AND q.available_at <= ?
                    AND q.room_id NOT IN (
                        SELECT room_id FROM message_queue WHERE status = 'processing'
                    )
                ORDER BY rooms.room_latest ASC, q.priority DESC, q.created_at DESC
                LIMIT 1
                """,
                (now, now),
            ).fetchone()

            # Fallback when every room already has an in-flight job.
            if not row:
                row = conn.execute(
                    """
                    SELECT q.id
                    FROM message_queue q
                    INNER JOIN (
                        SELECT room_id, MAX(created_at) AS room_latest
                        FROM message_queue
                        WHERE status = 'pending'
                            AND available_at <= ?
                        GROUP BY room_id
                    ) rooms ON rooms.room_id = q.room_id
                    WHERE q.status = 'pending'
                        AND q.available_at <= ?
                    ORDER BY rooms.room_latest ASC, q.priority DESC, q.created_at DESC
                    LIMIT 1
                    """,
                    (now, now),
                ).fetchone()

            if not row:
                conn.commit()
                return None

            job_id = int(row["id"])
            locked_until = now + lease_seconds
            conn.execute(
                """
                UPDATE message_queue
                SET status = 'processing',
                    locked_by = ?,
                    locked_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (consumer_id, locked_until, now, job_id),
            )

            job_row = self._fetch_job_row(conn, job_id)
            conn.commit()
            return _row_to_job(job_row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count_pending_rooms(self) -> int:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(DISTINCT room_id) AS c
                FROM message_queue
                WHERE status IN ('pending', 'processing')
                """
            ).fetchone()
        return int(row["c"] or 0) if row else 0

    def list_active_queue_room_ids(self) -> List[int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT DISTINCT room_id
                FROM message_queue
                WHERE status IN ('pending', 'processing')
                ORDER BY room_id ASC
                """
            ).fetchall()
        return [int(row["room_id"]) for row in rows]

    def skip_older_pending_for_room(
        self,
        room_id: int,
        before_job_id: int,
        *,
        keep_seconds: float = 0,
    ) -> int:
        """Mark/defer older pending jobs in the same room after a newer job finishes.

        keep_seconds > 0: giữ status=pending trên UI, hoãn claim; sau keep_seconds
        sẽ được finalize thành done (thu hồi).
        keep_seconds <= 0: thu hồi (done) ngay như trước.
        """
        now = _now()
        with self._connect() as conn:
            if keep_seconds and keep_seconds > 0:
                hold_until = now + float(keep_seconds)
                cursor = conn.execute(
                    """
                    UPDATE message_queue
                    SET available_at = CASE
                            WHEN available_at < ? THEN ?
                            ELSE available_at
                        END,
                        last_error = 'deferred supersede',
                        updated_at = ?
                    WHERE status = 'pending'
                        AND room_id = ?
                        AND id < ?
                        AND (
                            last_error IS NULL
                            OR last_error != 'deferred supersede'
                            OR available_at < ?
                        )
                    """,
                    (hold_until, hold_until, now, room_id, before_job_id, hold_until),
                )
                return int(cursor.rowcount)

            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    last_error = 'superseded by newer room message',
                    completed_at = ?,
                    updated_at = ?
                WHERE status = 'pending'
                    AND room_id = ?
                    AND id < ?
                """,
                (now, now, room_id, before_job_id),
            )
            return int(cursor.rowcount)

    def finalize_deferred_supersedes(self) -> int:
        """Thu hồi (done) các pending đã hết thời gian giữ sau deferred supersede."""
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    last_error = 'superseded by newer room message',
                    completed_at = ?,
                    updated_at = ?
                WHERE status = 'pending'
                    AND last_error = 'deferred supersede'
                    AND available_at <= ?
                """,
                (now, now, now),
            )
            return int(cursor.rowcount)

    def claim_next_newest(self, consumer_id: str, lease_seconds: int) -> Optional[QueueJob]:
        now = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._release_expired_jobs(conn, now)

            row = conn.execute(
                """
                SELECT id
                FROM message_queue
                WHERE status = 'pending'
                    AND available_at <= ?
                ORDER BY priority DESC, created_at DESC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if not row:
                conn.commit()
                return None

            job_id = int(row["id"])
            locked_until = now + lease_seconds
            conn.execute(
                """
                UPDATE message_queue
                SET status = 'processing',
                    locked_by = ?,
                    locked_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (consumer_id, locked_until, now, job_id),
            )

            job_row = self._fetch_job_row(conn, job_id)
            conn.commit()
            return _row_to_job(job_row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def skip_stale_pending_jobs(self, max_age_seconds: float) -> int:
        now = _now()
        cutoff = now - max_age_seconds
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    last_error = 'skipped stale pending',
                    completed_at = ?,
                    updated_at = ?
                WHERE status = 'pending'
                    AND created_at < ?
                """,
                (now, now, cutoff),
            )
            return int(cursor.rowcount)

    def claim_next_after(self, consumer_id: str, lease_seconds: int, after_id: int = 0) -> Optional[QueueJob]:
        now = _now()
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._release_expired_jobs(conn, now)

            row = conn.execute(
                """
                SELECT id
                FROM message_queue
                WHERE status = 'pending'
                    AND available_at <= ?
                    AND id > ?
                ORDER BY priority DESC, created_at DESC
                LIMIT 1
                """,
                (now, after_id),
            ).fetchone()
            if not row:
                conn.commit()
                return None

            job_id = int(row["id"])
            locked_until = now + lease_seconds
            conn.execute(
                """
                UPDATE message_queue
                SET status = 'processing',
                    locked_by = ?,
                    locked_until = ?,
                    attempts = attempts + 1,
                    updated_at = ?
                WHERE id = ?
                """,
                (consumer_id, locked_until, now, job_id),
            )

            job_row = self._fetch_job_row(conn, job_id)
            conn.commit()
            return _row_to_job(job_row)
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def renew_job_lease(self, job_id: int, consumer_id: str, lease_seconds: int) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET locked_until = ?,
                    updated_at = ?
                WHERE id = ?
                    AND status = 'processing'
                    AND locked_by = ?
                """,
                (now + lease_seconds, now, job_id, consumer_id),
            )
            return cursor.rowcount == 1

    def is_job_lock_valid(self, job_id: int, consumer_id: str) -> bool:
        now = _now()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT 1
                FROM message_queue
                WHERE id = ?
                    AND status = 'processing'
                    AND locked_by = ?
                    AND locked_until > ?
                """,
                (job_id, consumer_id, now),
            ).fetchone()
            return row is not None

    def mark_job_done(self, job_id: int, note: str = "") -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    completed_at = ?,
                    updated_at = ?,
                    locked_by = NULL,
                    locked_until = NULL,
                    last_error = ?
                WHERE id = ?
                """,
                (now, now, _truncate(note, 1000) if note else None, job_id),
            )
            return cursor.rowcount == 1

    def complete_job(self, job_id: int, consumer_id: str) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = 'done',
                    completed_at = ?,
                    updated_at = ?,
                    locked_by = NULL,
                    locked_until = NULL
                WHERE id = ?
                    AND status = 'processing'
                    AND locked_by = ?
                    AND locked_until > ?
                """,
                (now, now, job_id, consumer_id, now),
            )
            return cursor.rowcount == 1

    def fail_job(
        self,
        job_id: int,
        consumer_id: str,
        error_message: str,
        retry_delay_seconds: int,
    ) -> bool:
        now = _now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE message_queue
                SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
                    available_at = CASE WHEN attempts >= max_attempts THEN ? ELSE ? END,
                    updated_at = ?,
                    locked_by = NULL,
                    locked_until = NULL,
                    last_error = ?
                WHERE id = ?
                    AND status = 'processing'
                    AND locked_by = ?
                """,
                (
                    now,
                    now + retry_delay_seconds,
                    now,
                    _truncate(error_message, 1000),
                    job_id,
                    consumer_id,
                ),
            )
            return cursor.rowcount == 1

    def get_recent_messages(self, platform: str, chat_id: str, limit: int) -> List[HistoryMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    m.id,
                    m.direction,
                    m.text,
                    m.created_at,
                    u.user_id AS platform_user_id,
                    u.username
                FROM chat_messages m
                JOIN chat_rooms r ON r.id = m.room_id
                LEFT JOIN chat_users u ON u.id = m.user_id
                WHERE r.platform = ?
                    AND r.chat_id = ?
                ORDER BY m.created_at DESC
                LIMIT ?
                """,
                (platform, chat_id, limit),
            ).fetchall()

        return [
            HistoryMessage(
                id=int(row["id"]),
                direction=row["direction"],
                text=row["text"],
                created_at=float(row["created_at"]),
                platform_user_id=row["platform_user_id"],
                username=row["username"],
            )
            for row in reversed(rows)
        ]

    def get_queue_stats(self) -> Dict[str, int]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT status, COUNT(*) AS total
                FROM message_queue
                GROUP BY status
                """
            ).fetchall()

        return {row["status"]: int(row["total"]) for row in rows}

    def get_queue_items(
        self,
        limit: int,
        statuses: Optional[List[str]] = None,
        group: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        where_clauses: List[str] = []
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            where_clauses.append(f"q.status IN ({placeholders})")
            params.extend(statuses)

        if group:
            where_clauses.append("(r.chat_id = ? OR r.title = ? OR CAST(r.id AS TEXT) = ?)")
            params.extend([group, group, group])

        status_clause = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""

        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    q.id AS queue_id,
                    q.status,
                    q.priority,
                    q.payload_json,
                    q.attempts,
                    q.max_attempts,
                    q.locked_by,
                    q.locked_until,
                    q.available_at,
                    q.created_at AS queue_created_at,
                    q.updated_at AS queue_updated_at,
                    q.completed_at,
                    q.last_error,
                    r.id AS room_id,
                    r.platform AS room_platform,
                    r.chat_id AS room_chat_id,
                    r.chat_type AS room_chat_type,
                    r.title AS room_title,
                    m.id AS message_id,
                    m.platform_message_id,
                    m.direction AS message_direction,
                    m.text AS message_text,
                    m.created_at AS message_created_at,
                    u.user_id AS platform_user_id,
                    u.username,
                    u.first_name,
                    u.last_name
                FROM message_queue q
                JOIN chat_rooms r ON r.id = q.room_id
                JOIN chat_messages m ON m.id = q.message_id
                LEFT JOIN chat_users u ON u.id = m.user_id
                {status_clause}
                ORDER BY q.created_at DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        now = _now()
        return [_row_to_queue_item(row, now) for row in rows]

    def prune_queue(self, max_items: int) -> Dict[str, int]:
        with self._connect() as conn:
            queue_cursor = conn.execute(
                """
                DELETE FROM message_queue
                WHERE status != 'processing'
                  AND id NOT IN (
                      SELECT id
                      FROM message_queue
                      ORDER BY id DESC
                      LIMIT ?
                  )
                """,
                (max_items,),
            )
            message_cursor = conn.execute(
                """
                DELETE FROM chat_messages
                WHERE id NOT IN (
                    SELECT message_id
                    FROM message_queue
                )
                """
            )
            return {
                "queue": queue_cursor.rowcount,
                "messages": message_cursor.rowcount,
            }

    def prune_queue_older_than(self, max_age_seconds: int) -> Dict[str, int]:
        cutoff = _now() - max_age_seconds
        with self._connect() as conn:
            queue_cursor = conn.execute(
                """
                DELETE FROM message_queue
                WHERE status != 'processing'
                  AND created_at < ?
                """,
                (cutoff,),
            )
            message_cursor = conn.execute(
                """
                DELETE FROM chat_messages
                WHERE id NOT IN (
                    SELECT message_id
                    FROM message_queue
                )
                """
            )
            return {
                "queue": queue_cursor.rowcount,
                "messages": message_cursor.rowcount,
            }

    def prune_stale_telegram_pending(self, cutoff_timestamp_ms: int) -> Dict[str, int]:
        with self._connect() as conn:
            queue_cursor = conn.execute(
                """
                DELETE FROM message_queue
                WHERE status = 'pending'
                  AND json_extract(payload_json, '$.source') = 'telegram_web'
                  AND (
                    json_extract(payload_json, '$.telegram_timestamp_ms') IS NULL
                    OR CAST(
                      json_extract(payload_json, '$.telegram_timestamp_ms') AS INTEGER
                    ) < ?
                  )
                """,
                (cutoff_timestamp_ms,),
            )
            message_cursor = conn.execute(
                """
                DELETE FROM chat_messages
                WHERE id NOT IN (
                    SELECT message_id
                    FROM message_queue
                )
                """
            )
            return {
                "queue": queue_cursor.rowcount,
                "messages": message_cursor.rowcount,
            }

    def _release_expired_jobs(self, conn: sqlite3.Connection, now: float) -> int:
        cursor = conn.execute(
            """
            UPDATE message_queue
            SET status = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
                locked_by = NULL,
                locked_until = NULL,
                available_at = ?,
                updated_at = ?,
                last_error = COALESCE(last_error, 'Lease expired before completion')
            WHERE status = 'processing'
                AND locked_until IS NOT NULL
                AND locked_until <= ?
            """,
            (now, now, now),
        )
        return cursor.rowcount

    def _fetch_job_row(self, conn: sqlite3.Connection, job_id: int) -> sqlite3.Row:
        row = conn.execute(
            """
            SELECT
                q.*,
                m.text AS message_text,
                r.chat_id AS room_chat_id,
                u.user_id AS platform_user_id,
                u.username
            FROM message_queue q
            JOIN chat_messages m ON m.id = q.message_id
            JOIN chat_rooms r ON r.id = q.room_id
            LEFT JOIN chat_users u ON u.id = m.user_id
            WHERE q.id = ?
            """,
            (job_id,),
        ).fetchone()
        if not row:
            raise RuntimeError(f"Queue job not found: {job_id}")
        return row

    def vacuum(self) -> None:
        with self._connect() as conn:
            conn.execute("VACUUM")

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


def _row_to_job(row: sqlite3.Row) -> QueueJob:
    payload = json.loads(row["payload_json"] or "{}")
    return QueueJob(
        id=int(row["id"]),
        message_id=int(row["message_id"]),
        room_id=int(row["room_id"]),
        priority=int(row["priority"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        payload=payload,
        message_text=row["message_text"],
        room_chat_id=row["room_chat_id"],
        platform_user_id=row["platform_user_id"],
        username=row["username"],
        locked_until=float(row["locked_until"]),
    )


def _row_to_queue_item(row: sqlite3.Row, now: float) -> Dict[str, Any]:
    locked_until = _optional_float(row["locked_until"])
    lease_expired = (
        row["status"] == "processing"
        and locked_until is not None
        and locked_until <= now
    )

    return {
        "id": int(row["queue_id"]),
        "status": row["status"],
        "priority": int(row["priority"]),
        "attempts": int(row["attempts"]),
        "max_attempts": int(row["max_attempts"]),
        "locked_by": row["locked_by"],
        "locked_until": locked_until,
        "available_at": float(row["available_at"]),
        "created_at": float(row["queue_created_at"]),
        "updated_at": float(row["queue_updated_at"]),
        "completed_at": _optional_float(row["completed_at"]),
        "lease_expired": lease_expired,
        "last_error": row["last_error"],
        "payload": json.loads(row["payload_json"] or "{}"),
        "room": {
            "id": int(row["room_id"]),
            "platform": row["room_platform"],
            "chat_id": row["room_chat_id"],
            "chat_type": row["room_chat_type"],
            "title": row["room_title"],
        },
        "message": {
            "id": int(row["message_id"]),
            "platform_message_id": row["platform_message_id"],
            "direction": row["message_direction"],
            "text": row["message_text"],
            "created_at": float(row["message_created_at"]),
        },
        "user": {
            "platform_user_id": row["platform_user_id"],
            "username": row["username"],
            "first_name": row["first_name"],
            "last_name": row["last_name"],
        },
    }


def _optional_float(value: Optional[Any]) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _now() -> float:
    return time.time()


def _row_to_broadcast_bot(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "short_name": row["short_name"],
        "token": row["token"] or "",
        "telegram_username": row["telegram_username"],
        "telegram_display_name": row["telegram_display_name"],
        "enabled": bool(row["enabled"]),
        "sort_order": int(row["sort_order"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _normalize_broadcast_bot(raw: Dict[str, Any], now: float) -> Dict[str, Any]:
    short_name = str(raw.get("short_name") or "").strip().lower()
    if not short_name:
        raise ValueError("broadcast bot short_name is required")
    sort_order = raw.get("sort_order")
    try:
        sort_value = int(sort_order)
    except (TypeError, ValueError):
        match = None
        if short_name.startswith("b") and short_name[1:].isdigit():
            sort_value = int(short_name[1:])
        else:
            sort_value = 0
    return {
        "short_name": short_name,
        "token": str(raw.get("token") or "").strip(),
        "telegram_username": str(raw.get("telegram_username") or "").strip() or None,
        "telegram_display_name": str(raw.get("telegram_display_name") or "").strip() or None,
        "enabled": bool(raw.get("enabled", True)),
        "sort_order": sort_value,
        "created_at": float(raw.get("created_at") or now),
    }


def _default_reader_group_filter() -> Dict[str, Any]:
    return {
        "mode": "inherit",
        "filters": [],
        "reject": [],
    }


def _row_to_reader_group_filter(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        filters = json.loads(str(row["filters_json"] or "[]"))
    except json.JSONDecodeError:
        filters = []
    try:
        reject = json.loads(str(row["reject_json"] or "[]"))
    except json.JSONDecodeError:
        reject = []
    if not isinstance(filters, list):
        filters = []
    if not isinstance(reject, list):
        reject = []
    return {
        "mode": str(row["mode"] or "inherit"),
        "filters": filters,
        "reject": reject,
        "updated_at": float(row["updated_at"]),
    }


def _row_to_watch_group(row: sqlite3.Row) -> Dict[str, Any]:
    reader_id = "app1"
    if "reader_id" in row.keys():
        reader_id = str(row["reader_id"] or "app1").strip() or "app1"
    return {
        "id": int(row["id"]),
        "reader_id": reader_id,
        "name": row["name"],
        "chat_id": row["chat_id"],
        "enabled": bool(row["enabled"]),
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _normalize_watch_group(raw: Dict[str, Any], now: float) -> Dict[str, Any]:
    from config import normalize_client_chat_ref

    name = str(raw.get("name") or "").strip()
    chat_id = normalize_client_chat_ref(str(raw.get("chat_id") or "").strip())
    reader_id = str(raw.get("reader_id") or "app1").strip() or "app1"
    if not chat_id:
        raise ValueError("watch group chat_id is required")
    if not name:
        name = chat_id
    return {
        "reader_id": reader_id,
        "name": name,
        "chat_id": chat_id,
        "enabled": bool(raw.get("enabled", True)),
        "created_at": float(raw.get("created_at") or now),
    }


def _row_to_broadcast_group(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
        "name": row["name"],
        "chat_id": row["chat_id"],
        "enabled": bool(row["enabled"]),
        "approved": bool(row["approved"]) if "approved" in row.keys() else False,
        "created_at": float(row["created_at"]),
        "updated_at": float(row["updated_at"]),
    }


def _normalize_broadcast_group(raw: Dict[str, Any], now: float) -> Dict[str, Any]:
    name = str(raw.get("name") or "").strip()
    chat_id = str(raw.get("chat_id") or "").strip()
    if not name:
        raise ValueError("broadcast group name is required")
    if not chat_id:
        raise ValueError("broadcast group chat_id is required")
    try:
        int(chat_id)
    except ValueError as exc:
        raise ValueError(f"invalid broadcast group chat_id: {chat_id}") from exc
    return {
        "name": name,
        "chat_id": chat_id,
        "enabled": bool(raw.get("enabled", True)),
        "approved": bool(raw.get("approved", True)),
        "created_at": float(raw.get("created_at") or now),
    }


def _truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3] + "..."
