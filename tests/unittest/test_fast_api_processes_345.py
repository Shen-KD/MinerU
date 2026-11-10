"""Process separation for MinerU API frontends and the parsing worker."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from mineru.cli import fast_api


def make_task(task_id: str, output_dir: str) -> fast_api.AsyncParseTask:
    return fast_api.AsyncParseTask(
        task_id=task_id,
        status=fast_api.TASK_PENDING,
        backend="hybrid-engine",
        file_names=[],
        created_at=fast_api.utc_now_iso(),
        output_dir=output_dir,
        effort="medium",
        parse_method="auto",
        lang_list=["ch"],
        formula_enable=True,
        table_enable=True,
        image_analysis=False,
        server_url=None,
        return_md=True,
        return_middle_json=False,
        return_model_output=False,
        return_content_list=False,
        return_images=False,
        response_format_zip=True,
        return_original_file=False,
        client_side_output_generation=False,
        start_page_id=0,
        end_page_id=0,
        upload_names=[],
        uploads=[],
    )


@pytest.mark.asyncio
async def test_api_process_only_enqueues_and_parser_process_controls_concurrency(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_API_TASK_DB_PATH", str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setenv("MINERU_API_TASK_RETENTION_SECONDS", "3600")
    app = fast_api.FastAPI()
    app.state.config = {}
    api = fast_api.AsyncTaskManager(app, enable_parsing=False)
    parser = fast_api.AsyncTaskManager(app, enable_parsing=True, max_concurrent_requests=2)
    active = 0
    max_active = 0

    async def fake_parse(**kwargs):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.08)
        active -= 1

    monkeypatch.setattr(fast_api, "run_parse_job", fake_parse)
    await api.start()
    try:
        for index in range(5):
            await api.submit(make_task(f"task-{index}", str(tmp_path)))
        await asyncio.sleep(0.05)
        assert api.get("task-0").status == fast_api.TASK_PENDING
        assert api.get_stats()[fast_api.TASK_PENDING] == 5
        assert api.is_healthy() is True

        await parser.start()
        deadline = asyncio.get_running_loop().time() + 5
        while api.get_stats()[fast_api.TASK_COMPLETED] < 5:
            assert asyncio.get_running_loop().time() < deadline, api.get_stats()
            await asyncio.sleep(0.02)

        assert max_active == 2
        assert all(api.get(f"task-{index}").status == fast_api.TASK_COMPLETED for index in range(5))
    finally:
        await parser.shutdown()
        await api.shutdown()


@pytest.mark.asyncio
async def test_api_startup_does_not_preload_models(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_API_TASK_DB_PATH", str(tmp_path / "tasks.sqlite3"))
    preload = Mock()
    monkeypatch.setattr(fast_api, "maybe_preload_vlm_model", preload)
    app = fast_api.FastAPI()
    app.state.service_config = {"enable_vlm_preload": True}
    app.state.config = {}

    manager = await fast_api.startup_app_state(app)
    try:
        assert manager.enable_parsing is False
        preload.assert_not_called()
    finally:
        await fast_api.shutdown_app_state(app)


def test_workers_option_controls_only_uvicorn_workers(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MINERU_API_TASK_DB_PATH", str(tmp_path / "tasks.sqlite3"))
    monkeypatch.setattr(fast_api, "arg_parse", lambda ctx: {})
    uvicorn_run = Mock()
    monkeypatch.setattr(fast_api.uvicorn, "run", uvicorn_run)
    process = Mock()
    process.is_alive.return_value = False
    context = Mock()
    context.Process.return_value = process
    monkeypatch.setattr(fast_api.multiprocessing, "get_context", lambda method: context)

    result = CliRunner().invoke(fast_api.main, ["--workers", "3"])

    assert result.exit_code == 0, result.output
    assert uvicorn_run.call_args.kwargs["workers"] == 3
    process.start.assert_called_once_with()
    process.terminate.assert_called_once_with()
    process.join.assert_called_once()
