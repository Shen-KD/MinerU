"""Ensure the 4.x heap-trim lifecycle is wired into the 3.4.5 backends."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _function(path: str, name: str) -> ast.AST:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    return next(node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def _trim_calls(function: ast.AST) -> list[ast.Call]:
    return [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "trim_process_heap"
    ]


@pytest.mark.parametrize("path", ["mineru/backend/hybrid/hybrid_analyze.py", "mineru/backend/vlm/vlm_analyze.py"])
@pytest.mark.parametrize("function_name", ["doc_analyze", "aio_doc_analyze"])
def test_window_and_document_cleanup_trim_hybrid_and_vlm(path: str, function_name: str) -> None:
    function = _function(path, function_name)
    calls = _trim_calls(function)
    assert len(calls) == 2, "each window and the outer document cleanup must each trim once"


def test_window_and_document_cleanup_trim_pipeline() -> None:
    path = "mineru/backend/pipeline/pipeline_analyze.py"
    stream = _function(path, "doc_analyze_streaming")
    finalize = _function(path, "_finalize_processing_window_context")
    assert len(_trim_calls(stream)) == 2, "each batch and exceptional document cleanup must trim"
    assert len(_trim_calls(finalize)) == 1, "successful per-document cleanup must trim"
