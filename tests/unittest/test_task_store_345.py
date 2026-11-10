"""SQLite-backed queue shared by API frontend and parser processes."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from mineru.cli.task_store import SQLiteTaskStore


def payload(task_id: str) -> dict:
    return {
        "task_id": task_id,
        "status": "pending",
        "created_at": "2026-11-10T00:00:00+00:00",
        "file_names": [f"{task_id}.pdf"],
        "output_dir": f"/tmp/{task_id}",
    }


def test_submit_is_visible_across_store_instances_and_preserves_fifo(tmp_path) -> None:
    path = tmp_path / "tasks.sqlite3"
    api_1 = SQLiteTaskStore(path)
    api_2 = SQLiteTaskStore(path)
    order_1 = api_1.submit(payload("task-1"))
    order_2 = api_2.submit(payload("task-2"))

    assert order_2 > order_1
    assert api_2.get("task-1")["payload"]["file_names"] == ["task-1.pdf"]
    assert api_1.count_queued_ahead("task-1") == 0
    assert api_1.count_queued_ahead("task-2") == 1
    assert api_2.stats() == {"pending": 2, "processing": 0, "completed": 0, "failed": 0}


def test_claim_next_is_atomic_across_connections(tmp_path) -> None:
    path = tmp_path / "tasks.sqlite3"
    SQLiteTaskStore(path).submit(payload("only-task"))

    def claim() -> dict | None:
        return SQLiteTaskStore(path).claim_next()

    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: claim(), range(8)))

    assert sum(claim is not None for claim in claims) == 1
    record = SQLiteTaskStore(path).get("only-task")
    assert record["status"] == "processing"
    assert record["started_at"] is not None


def test_terminal_states_stats_retention_and_delete(tmp_path) -> None:
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite3")
    store.submit(payload("done"))
    store.submit(payload("failed"))
    store.submit(payload("pending"))

    assert store.claim_next()["task_id"] == "done"
    store.mark_completed("done", "2026-11-10T01:00:00+00:00")
    assert store.claim_next()["task_id"] == "failed"
    store.mark_failed("failed", "boom", "2026-11-10T01:01:00+00:00")

    assert store.stats() == {"pending": 1, "processing": 0, "completed": 1, "failed": 1}
    expired = store.expired_terminal("2026-11-10T02:00:00+00:00")
    assert {record["task_id"] for record in expired} == {"done", "failed"}
    store.delete("done")
    assert store.get("done") is None
    assert store.get("pending")["status"] == "pending"


def test_requeue_processing_recovers_interrupted_parser(tmp_path) -> None:
    store = SQLiteTaskStore(tmp_path / "tasks.sqlite3")
    store.submit(payload("interrupted"))
    assert store.claim_next()["status"] == "processing"

    assert store.requeue_processing() == 1
    record = store.get("interrupted")
    assert record["status"] == "pending"
    assert record["started_at"] is None
    assert store.claim_next()["task_id"] == "interrupted"
