import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from config import QueueJsonConfig, load_queue_json_config
from db import ChatDatabase


logger = logging.getLogger(__name__)


class QueueJsonClient:
    def __init__(self, config: QueueJsonConfig):
        self.config = config
        self.db = ChatDatabase(config.db_path)
        self.output_path = Path(config.output_path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_signature: str = ""

    def run_forever(self) -> None:
        self.db.init_schema()
        logger.info("Writing queue snapshots to %s", self.output_path)

        while True:
            self.write_snapshot()
            time.sleep(self.config.poll_interval_seconds)

    def write_snapshot(self) -> None:
        snapshot = self.build_snapshot()
        signature = self._snapshot_signature(snapshot)
        if signature == self._last_signature:
            logger.debug("Queue snapshot unchanged path=%s", self.output_path)
            return

        tmp_path = self.output_path.with_suffix(self.output_path.suffix + ".tmp")
        indent = 2 if self.config.pretty else None

        tmp_path.write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=indent) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.output_path)
        self._last_signature = signature
        logger.debug(
            "Queue snapshot written path=%s items=%s",
            self.output_path,
            len(snapshot["items"]),
        )

    def build_snapshot(self) -> Dict[str, Any]:
        statuses = list(self.config.statuses)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "db_path": self.config.db_path,
            "limit": self.config.limit,
            "statuses": statuses,
            "stats": self.db.get_queue_stats(),
            "items": self.db.get_queue_items(
                limit=self.config.limit,
                statuses=statuses or None,
            ),
        }

    def _snapshot_signature(self, snapshot: Dict[str, Any]) -> str:
        items = snapshot.get("items", [])
        latest = [
            (
                item.get("id"),
                item.get("status"),
                item.get("attempts"),
                item.get("updated_at"),
            )
            for item in items
        ]
        stats = sorted((snapshot.get("stats") or {}).items())
        return json.dumps([stats, latest], ensure_ascii=False, separators=(",", ":"))


def setup_logging(log_level: str) -> None:
    level = getattr(logging, log_level, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def main() -> None:
    config = load_queue_json_config()
    setup_logging(config.log_level)
    QueueJsonClient(config).run_forever()


if __name__ == "__main__":
    main()
