"""SQLite task queue shared by MinerU API frontend and parser processes."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


TERMINAL_STATUSES = ("completed", "failed")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SQLiteTaskStore:
    """A small, multi-process-safe FIFO queue and task metadata store."""

    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA synchronous=NORMAL")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    submit_order INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    payload TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_queue
                    ON tasks(status, submit_order);
                CREATE INDEX IF NOT EXISTS idx_tasks_retention
                    ON tasks(status, completed_at);
                """
            )

    @staticmethod
    def _record(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return {
            "task_id": row["task_id"],
            "submit_order": row["submit_order"],
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "error": row["error"],
            "payload": json.loads(row["payload"]),
        }

    def submit(self, payload: dict[str, Any]) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO tasks(task_id, status, created_at, payload) VALUES (?, ?, ?, ?)",
                (
                    payload["task_id"],
                    payload["status"],
                    payload["created_at"],
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            return int(cursor.lastrowid)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
        return self._record(row)

    def count_queued_ahead(self, task_id: str) -> int | None:
        with self._connect() as connection:
            row = connection.execute("SELECT submit_order FROM tasks WHERE task_id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE status = 'pending' AND submit_order < ?",
                (row["submit_order"],),
            ).fetchone()[0]

    def stats(self) -> dict[str, int]:
        with self._connect() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS count FROM tasks GROUP BY status").fetchall()
        result = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
        for row in rows:
            if row["status"] in result:
                result[row["status"]] = row["count"]
        return result

    def claim_next(self) -> dict[str, Any] | None:
        """Atomically claim the oldest pending task and mark it processing."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT * FROM tasks WHERE status = 'pending' ORDER BY submit_order LIMIT 1"
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                started_at = utc_now_iso()
                updated = connection.execute(
                    "UPDATE tasks SET status = 'processing', started_at = ?, error = NULL "
                    "WHERE task_id = ? AND status = 'pending'",
                    (started_at, row["task_id"]),
                )
                if updated.rowcount != 1:
                    connection.rollback()
                    return None
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return self.get(row["task_id"])

    def mark_completed(self, task_id: str, completed_at: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'completed', completed_at = ?, error = NULL WHERE task_id = ?",
                (completed_at or utc_now_iso(), task_id),
            )

    def mark_failed(self, task_id: str, error: str, completed_at: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = 'failed', completed_at = ?, error = ? WHERE task_id = ?",
                (completed_at or utc_now_iso(), error, task_id),
            )

    def expired_terminal(self, completed_before: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE status IN (?, ?) AND completed_at IS NOT NULL AND completed_at <= ? "
                "ORDER BY submit_order",
                (*TERMINAL_STATUSES, completed_before),
            ).fetchall()
        return [self._record(row) for row in rows]

    def delete(self, task_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def requeue_processing(self) -> int:
        """Return interrupted tasks to the FIFO when the sole parser starts."""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE tasks SET status = 'pending', started_at = NULL, error = NULL WHERE status = 'processing'"
            )
            return cursor.rowcount
