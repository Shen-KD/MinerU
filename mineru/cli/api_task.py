"""Task data contracts shared by MinerU HTTP and parser processes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class StoredUpload:
    original_name: str
    stem: str
    path: str


@dataclass
class AsyncParseTask:
    task_id: str
    status: str
    backend: str
    file_names: list[str]
    created_at: str
    output_dir: str
    effort: str
    parse_method: str
    lang_list: list[str]
    formula_enable: bool
    table_enable: bool
    image_analysis: bool
    server_url: Optional[str]
    return_md: bool
    return_middle_json: bool
    return_model_output: bool
    return_content_list: bool
    return_images: bool
    response_format_zip: bool
    return_original_file: bool
    client_side_output_generation: bool
    start_page_id: int
    end_page_id: int
    upload_names: list[str]
    uploads: list[str]
    submit_order: int = 0
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None

    def to_status_payload(self, request: Any, queued_ahead: int | None = None) -> dict[str, Any]:
        payload = {
            "task_id": self.task_id,
            "status": self.status,
            "backend": self.backend,
            "file_names": self.file_names,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "status_url": str(request.url_for("get_async_task_status", task_id=self.task_id)),
            "result_url": str(request.url_for("get_async_task_result", task_id=self.task_id)),
        }
        if queued_ahead is not None:
            payload["queued_ahead"] = queued_ahead
        return payload
