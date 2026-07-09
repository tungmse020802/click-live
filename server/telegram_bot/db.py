import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


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
    ) -> Optional[int]:
        now = _now()
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

    def list_watch_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, created_at, updated_at
                FROM watch_groups
                ORDER BY name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_watch_group(row) for row in rows]

    def list_enabled_watch_groups(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, name, chat_id, enabled, created_at, updated_at
                FROM watch_groups
                WHERE enabled = 1
                ORDER BY name ASC, id ASC
                """
            ).fetchall()
        return [_row_to_watch_group(row) for row in rows]

    def replace_watch_groups(self, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = _now()
        normalized = [_normalize_watch_group(raw, now) for raw in groups]
        with self._connect() as conn:
            conn.execute("DELETE FROM watch_groups")
            for group in normalized:
                conn.execute(
                    """
                    INSERT INTO watch_groups(name, chat_id, enabled, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        group["name"],
                        group["chat_id"],
                        1 if group.get("enabled", True) else 0,
                        group.get("created_at", now),
                        now,
                    ),
                )
        return self.list_watch_groups()

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
        """Claim newest pending job from the room waiting longest (fair across rooms)."""
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

    def skip_older_pending_for_room(self, room_id: int, before_job_id: int) -> int:
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
                    AND room_id = ?
                    AND id < ?
                """,
                (now, now, room_id, before_job_id),
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
    ) -> List[Dict[str, Any]]:
        params: List[Any] = []
        status_clause = ""
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            status_clause = f"WHERE q.status IN ({placeholders})"
            params.extend(statuses)

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


def _row_to_watch_group(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": int(row["id"]),
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
    if not chat_id:
        raise ValueError("watch group chat_id is required")
    if not name:
        name = chat_id
    return {
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
