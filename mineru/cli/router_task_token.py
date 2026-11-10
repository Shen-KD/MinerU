"""Signed, stateless upstream task addressing for router replicas."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any


_VERSION = "v1"
_REQUIRED_FIELDS = ("s", "u", "t", "c")


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _signature(payload: str, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).digest())


def encode_task_token(payload: dict[str, Any], secret: str) -> str:
    if not secret:
        raise ValueError("A non-empty router task secret is required")
    compact = {key: payload[key] for key in _REQUIRED_FIELDS}
    encoded_payload = _b64encode(json.dumps(compact, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    return f"{_VERSION}.{encoded_payload}.{_signature(encoded_payload, secret)}"


def decode_task_token(token: str, secret: str) -> dict[str, Any]:
    if not secret:
        raise ValueError("A non-empty router task secret is required")
    try:
        version, encoded_payload, signature = token.split(".")
    except ValueError as exc:
        raise ValueError("Invalid router task token") from exc
    if version != _VERSION:
        raise ValueError("Unsupported router task token version")
    expected = _signature(encoded_payload, secret)
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid router task token signature")
    try:
        payload = json.loads(_b64decode(encoded_payload))
    except Exception as exc:
        raise ValueError("Invalid router task token payload") from exc
    if not isinstance(payload, dict) or any(not isinstance(payload.get(key), str) or not payload[key] for key in _REQUIRED_FIELDS):
        raise ValueError("Invalid router task token fields")
    return payload
