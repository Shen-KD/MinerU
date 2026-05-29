#!/usr/bin/env python3
"""Smoke-test mineru-api import/startup under common Docker env settings."""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def reload_fast_api():
    for name in list(sys.modules):
        if name == "mineru.cli.fast_api" or name.startswith("mineru.cli.fast_api."):
            del sys.modules[name]
    return importlib.import_module("mineru.cli.fast_api")


def check_env(label: str, env: dict[str, str | None]) -> None:
    saved = {key: os.environ.get(key) for key in env}
    try:
        for key, value in env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        module = reload_fast_api()
        semaphore = module._request_semaphore
        configured = module._configured_max_concurrent_requests
        print(f"[OK] {label}: max_concurrent_requests={configured}, semaphore={semaphore!r}")
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def check_config_reader() -> None:
    saved = os.environ.get("MINERU_API_MAX_CONCURRENT_REQUESTS")
    try:
        os.environ["MINERU_API_MAX_CONCURRENT_REQUESTS"] = "0"
        from mineru.utils.config_reader import get_max_concurrent_requests

        value = get_max_concurrent_requests()
        if value != 0:
            raise AssertionError(f"expected 0 for unlimited, got {value}")
        print("[OK] config_reader: MINERU_API_MAX_CONCURRENT_REQUESTS=0 -> unlimited")
    finally:
        if saved is None:
            os.environ.pop("MINERU_API_MAX_CONCURRENT_REQUESTS", None)
        else:
            os.environ["MINERU_API_MAX_CONCURRENT_REQUESTS"] = saved


def main() -> int:
    os.chdir(ROOT)
    check_config_reader()
    check_env("default", {"MINERU_API_MAX_CONCURRENT_REQUESTS": None})
    check_env("docker-unlimited", {"MINERU_API_MAX_CONCURRENT_REQUESTS": "0"})
    check_env("limited", {"MINERU_API_MAX_CONCURRENT_REQUESTS": "4"})

    help_proc = subprocess.run(
        [sys.executable, "-m", "mineru.cli.fast_api", "--help"],
        env={**os.environ, "MINERU_API_MAX_CONCURRENT_REQUESTS": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    if help_proc.returncode != 0:
        print(help_proc.stdout)
        print(help_proc.stderr, file=sys.stderr)
        return 1
    print("[OK] mineru.cli.fast_api --help with MINERU_API_MAX_CONCURRENT_REQUESTS=0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
