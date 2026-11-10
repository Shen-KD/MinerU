"""MinerU 3.4.5 backport: optional glibc heap trimming."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from mineru.utils import model_utils as memory


@pytest.fixture(autouse=True)
def isolate_allocator(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    memory._get_malloc_trim.cache_clear()
    monkeypatch.delenv("MINERU_MALLOC_TRIM", raising=False)
    monkeypatch.setattr(memory, "sys", SimpleNamespace(platform="linux"))
    yield
    memory._get_malloc_trim.cache_clear()


def test_trim_process_heap_is_available_and_disabled_by_default() -> None:
    assert hasattr(memory, "trim_process_heap")
    assert memory.trim_process_heap() is False


@pytest.mark.parametrize("value", [None, "", "0", "false", "no", "off", "disabled", "invalid", "2"])
def test_disabled_trim_does_not_load_allocator(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is not None:
        monkeypatch.setenv("MINERU_MALLOC_TRIM", value)
    load = Mock(side_effect=AssertionError("must not load libc"))
    monkeypatch.setattr(ctypes, "CDLL", load)
    assert memory.trim_process_heap() is False
    load.assert_not_called()


@pytest.mark.parametrize("value", ["1", "true", "YES", " On "])
@pytest.mark.parametrize("released", [0, 1])
def test_enabled_trim_caches_signature_but_not_switch(monkeypatch: pytest.MonkeyPatch, value: str, released: int) -> None:
    malloc_trim = Mock(return_value=released)
    load = Mock(return_value=SimpleNamespace(malloc_trim=malloc_trim))
    monkeypatch.setattr(ctypes, "CDLL", load)
    monkeypatch.setenv("MINERU_MALLOC_TRIM", value)
    assert memory.trim_process_heap() is bool(released)
    assert memory.trim_process_heap() is bool(released)
    load.assert_called_once_with(None)
    assert malloc_trim.argtypes == [ctypes.c_size_t]
    assert malloc_trim.restype is ctypes.c_int
    assert malloc_trim.call_count == 2
    malloc_trim.assert_called_with(0)
    monkeypatch.setenv("MINERU_MALLOC_TRIM", "0")
    assert memory.trim_process_heap() is False
    assert malloc_trim.call_count == 2


@pytest.mark.parametrize("platform", ["darwin", "win32"])
def test_unsupported_platform_does_not_load_libc(monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
    monkeypatch.setenv("MINERU_MALLOC_TRIM", "1")
    monkeypatch.setattr(memory, "sys", SimpleNamespace(platform=platform))
    load = Mock(side_effect=AssertionError("must not load libc"))
    monkeypatch.setattr(ctypes, "CDLL", load)
    assert memory.trim_process_heap() is False
    load.assert_not_called()


@pytest.mark.parametrize("failure", ["load", "symbol", "call"])
def test_allocator_failures_are_optional(monkeypatch: pytest.MonkeyPatch, failure: str) -> None:
    monkeypatch.setenv("MINERU_MALLOC_TRIM", "1")
    library = SimpleNamespace()
    if failure == "call":
        library.malloc_trim = Mock(side_effect=RuntimeError("allocator failed"))
    load = Mock(side_effect=OSError("no libc")) if failure == "load" else Mock(return_value=library)
    monkeypatch.setattr(ctypes, "CDLL", load)
    assert memory.trim_process_heap() is False
    assert memory.trim_process_heap() is False
    load.assert_called_once_with(None)


def test_trim_import_and_call_do_not_load_torch() -> None:
    code = """
import os
import sys
before = dict(os.environ)
from mineru.utils.model_utils import trim_process_heap
assert dict(os.environ) == before
assert trim_process_heap() is False
assert 'torch' not in sys.modules
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "MINERU_MALLOC_TRIM": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
