"""Stateless task addressing for multi-worker and multi-replica routers."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from mineru.cli import router
from mineru.cli.router_task_token import decode_task_token, encode_task_token


def test_signed_task_token_round_trip_and_tamper_rejection() -> None:
    payload = {
        "s": "remote-2",
        "u": "http://worker-2:8000",
        "t": "upstream-task-id",
        "c": "2026-11-10T00:00:00+00:00",
    }
    token = encode_task_token(payload, "shared-secret")

    assert decode_task_token(token, "shared-secret") == payload
    with pytest.raises(ValueError, match="signature"):
        decode_task_token(token, "wrong-secret")
    with pytest.raises(ValueError):
        decode_task_token(token[:-1] + ("A" if token[-1] != "A" else "B"), "shared-secret")


@pytest.mark.asyncio
async def test_registry_restores_task_on_another_router_replica() -> None:
    first = router.RouterTaskRegistry(
        task_retention_seconds=3600,
        cleanup_interval_seconds=60,
        task_secret="shared-secret",
    )
    second = router.RouterTaskRegistry(
        task_retention_seconds=3600,
        cleanup_interval_seconds=60,
        task_secret="shared-secret",
    )
    registered = await first.register(
        upstream_server_id="remote-2",
        upstream_base_url="http://worker-2:8000",
        upstream_task_id="upstream-task-id",
        backend="hybrid-engine",
        file_names=["document.pdf"],
        created_at="2026-11-10T00:00:00+00:00",
        status="pending",
        started_at=None,
        completed_at=None,
        error=None,
        queued_ahead=0,
    )

    restored = await second.get(registered.task_id)
    assert restored is not None
    assert restored.upstream_base_url == "http://worker-2:8000"
    assert restored.upstream_task_id == "upstream-task-id"
    assert restored.status == "pending"

    updated = await second.update_from_upstream_payload(
        registered.task_id,
        {
            "status": "completed",
            "backend": "hybrid-engine",
            "file_names": ["document.pdf"],
            "created_at": "2026-11-10T00:00:00+00:00",
            "completed_at": "2026-11-10T00:01:00+00:00",
        },
    )
    assert updated.status == "completed"
    assert (await second.get(registered.task_id)).status == "completed"


def test_router_workers_option_requires_shared_secret_and_remote_upstreams(monkeypatch) -> None:
    uvicorn_run = Mock()
    monkeypatch.setattr(router.uvicorn, "run", uvicorn_run)
    monkeypatch.setenv("MINERU_ROUTER_TASK_SECRET", "shared-secret")

    result = CliRunner().invoke(
        router.main,
        ["--workers", "3", "--local-gpus", "none", "--upstream-url", "http://worker-1:8000"],
    )

    assert result.exit_code == 0, result.output
    assert uvicorn_run.call_args.kwargs["workers"] == 3


def test_router_multiple_workers_rejects_missing_secret(monkeypatch) -> None:
    monkeypatch.delenv("MINERU_ROUTER_TASK_SECRET", raising=False)
    uvicorn_run = Mock()
    monkeypatch.setattr(router.uvicorn, "run", uvicorn_run)

    result = CliRunner().invoke(
        router.main,
        ["--workers", "2", "--local-gpus", "none", "--upstream-url", "http://worker-1:8000"],
    )

    assert result.exit_code != 0
    assert "MINERU_ROUTER_TASK_SECRET" in result.output
    uvicorn_run.assert_not_called()
