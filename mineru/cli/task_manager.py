"""Multi-process task manager for MinerU API frontends and the parser process."""

from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI
from loguru import logger

from mineru.cli.api_task import AsyncParseTask, StoredUpload
from mineru.cli.task_store import SQLiteTaskStore, utc_now_iso
from mineru.utils.config_reader import get_max_concurrent_requests

TASK_PENDING = "pending"
TASK_PROCESSING = "processing"
TASK_COMPLETED = "completed"
TASK_FAILED = "failed"
TASK_TERMINAL_STATES = {TASK_COMPLETED, TASK_FAILED}
DEFAULT_TASK_RETENTION_SECONDS = 24 * 60 * 60
DEFAULT_TASK_CLEANUP_INTERVAL_SECONDS = 5 * 60


def get_int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return value if value >= minimum else default


def get_task_db_path() -> Path:
    configured = os.getenv("MINERU_API_TASK_DB_PATH")
    if configured:
        return Path(configured).expanduser().resolve()
    output_root = Path(os.getenv("MINERU_API_OUTPUT_ROOT", "./output")).expanduser().resolve()
    return output_root / "tasks.sqlite3"


def cleanup_file(file_path: str) -> None:
    try:
        path = Path(file_path)
        if path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)
    except Exception as exc:
        logger.warning(f"fail clean file {file_path}: {exc}")


class TaskWaitAbortedError(RuntimeError):
    pass


class AsyncTaskManager:
    """Share one SQLite queue between API-only and parser-only processes."""

    def __init__(
        self,
        fastapi_app: FastAPI,
        *,
        enable_parsing: bool = False,
        max_concurrent_requests: int | None = None,
    ):
        self.app = fastapi_app
        self.enable_parsing = enable_parsing
        self.max_concurrent_requests = max_concurrent_requests or get_max_concurrent_requests(default=3)
        if self.max_concurrent_requests <= 0:
            raise ValueError("max_concurrent_requests must be a positive integer")
        self.store = SQLiteTaskStore(get_task_db_path())
        self.dispatcher_task: Optional[asyncio.Task[Any]] = None
        self.cleanup_task: Optional[asyncio.Task[Any]] = None
        self.active_tasks: set[asyncio.Task[Any]] = set()
        self.last_worker_error: Optional[str] = None
        self.is_shutting_down = False
        self.task_retention_seconds = get_int_env(
            "MINERU_API_TASK_RETENTION_SECONDS",
            DEFAULT_TASK_RETENTION_SECONDS,
            minimum=0,
        )
        self.task_cleanup_interval_seconds = get_int_env(
            "MINERU_API_TASK_CLEANUP_INTERVAL_SECONDS",
            DEFAULT_TASK_CLEANUP_INTERVAL_SECONDS,
            minimum=1,
        )

    @staticmethod
    def _record_to_task(record: dict[str, Any] | None) -> AsyncParseTask | None:
        if record is None:
            return None
        payload = dict(record["payload"])
        payload.update(
            status=record["status"],
            submit_order=record["submit_order"],
            started_at=record["started_at"],
            completed_at=record["completed_at"],
            error=record["error"],
        )
        return AsyncParseTask(**payload)

    async def start(self) -> None:
        self.is_shutting_down = False
        self.last_worker_error = None
        if not self.enable_parsing:
            return
        self.store.requeue_processing()
        if self.dispatcher_task is None or self.dispatcher_task.done():
            self.dispatcher_task = asyncio.create_task(self._dispatcher_loop(), name="mineru-parser-dispatcher")
        if self.task_retention_seconds > 0 and (self.cleanup_task is None or self.cleanup_task.done()):
            self.cleanup_task = asyncio.create_task(self._cleanup_loop(), name="mineru-parser-task-cleanup")

    async def shutdown(self) -> None:
        self.is_shutting_down = True
        for task_name in ("dispatcher_task", "cleanup_task"):
            task = getattr(self, task_name)
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                setattr(self, task_name, None)
        active = list(self.active_tasks)
        for processor in active:
            processor.cancel()
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        self.active_tasks.clear()

    async def submit(self, task: AsyncParseTask) -> None:
        task.submit_order = self.store.submit(asdict(task))

    def get(self, task_id: str) -> Optional[AsyncParseTask]:
        return self._record_to_task(self.store.get(task_id))

    def get_queued_ahead(self, task_id: str) -> int | None:
        task = self.get(task_id)
        if task is None:
            return None
        if task.status != TASK_PENDING:
            return 0
        return self.store.count_queued_ahead(task_id)

    def build_status_payload(self, task: AsyncParseTask, request: Any) -> dict[str, Any]:
        return task.to_status_payload(request, queued_ahead=self.get_queued_ahead(task.task_id))

    async def wait_for_terminal_state(self, task_id: str) -> AsyncParseTask:
        while True:
            task = self.get(task_id)
            if task is None:
                raise TaskWaitAbortedError("Task not found")
            if task.status in TASK_TERMINAL_STATES:
                return task
            if self.is_shutting_down:
                raise TaskWaitAbortedError("Task manager is shutting down")
            await asyncio.sleep(0.2)

    def get_stats(self) -> dict[str, int]:
        return self.store.stats()

    def is_healthy(self) -> bool:
        if self.is_shutting_down:
            return False
        if not self.enable_parsing:
            return True
        if self.dispatcher_task is None or self.dispatcher_task.done():
            return False
        if self.task_retention_seconds > 0 and (self.cleanup_task is None or self.cleanup_task.done()):
            return False
        return self.last_worker_error is None

    async def _dispatcher_loop(self) -> None:
        try:
            while True:
                claimed = False
                while len(self.active_tasks) < self.max_concurrent_requests:
                    record = self.store.claim_next()
                    if record is None:
                        break
                    claimed = True
                    task = self._record_to_task(record)
                    processor = asyncio.create_task(
                        self._run_claimed_task(task),
                        name=f"mineru-parser-task-{task.task_id}",
                    )
                    self.active_tasks.add(processor)
                    processor.add_done_callback(self._on_processor_done)
                await asyncio.sleep(0.02 if claimed else 0.1)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_worker_error = str(exc)
            logger.exception("Async parser dispatcher crashed")
            raise

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                await asyncio.sleep(self.task_cleanup_interval_seconds)
                self.cleanup_expired_tasks()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_worker_error = str(exc)
            logger.exception("Async task cleanup loop crashed")
            raise

    def _on_processor_done(self, processor: asyncio.Task[Any]) -> None:
        self.active_tasks.discard(processor)
        if processor.cancelled():
            return
        exception = processor.exception()
        if exception is not None:
            self.last_worker_error = str(exception)
            logger.error(f"Async task processor crashed: {exception}")

    async def _run_claimed_task(self, task: AsyncParseTask) -> None:
        try:
            await self._run_task(task)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.store.mark_failed(task.task_id, str(exc))
            logger.exception(f"Async task failed: {task.task_id}")
        else:
            self.store.mark_completed(task.task_id)

    async def _run_task(self, task: AsyncParseTask) -> None:
        from mineru.cli.fast_api import run_parse_job

        uploads = [
            StoredUpload(original_name=upload_name, stem=file_name, path=upload_path)
            for upload_name, file_name, upload_path in zip(task.upload_names, task.file_names, task.uploads)
        ]
        config = getattr(self.app.state, "config", {})
        await run_parse_job(output_dir=task.output_dir, uploads=uploads, request_options=task, config=config)

    def cleanup_expired_tasks(self) -> int:
        if self.task_retention_seconds <= 0:
            return 0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=self.task_retention_seconds)
        expired = self.store.expired_terminal(cutoff.isoformat())
        for record in expired:
            self.store.delete(record["task_id"])
            cleanup_file(record["payload"]["output_dir"])
            logger.info(f"Cleaned expired async task: {record['task_id']}")
        return len(expired)
