"""Shared argument validation helpers for the tool layer."""

from __future__ import annotations

import re
from typing import Any

from app.errors import ErrorCodes, ToolResult

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"\d{2}:\d{2}")


def require_dict(args: Any, tool: str) -> ToolResult | None:
    if not isinstance(args, dict):
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            f"{tool}: arguments must be a JSON object, got {type(args).__name__}",
        )
    return None


def require_keys(args: dict, tool: str, *keys: str) -> ToolResult | None:
    missing = [k for k in keys if k not in args or args[k] is None]
    if missing:
        return ToolResult.failure(
            ErrorCodes.MISSING_ARGUMENT,
            f"{tool}: missing required argument(s): {', '.join(missing)}",
        )
    return None


def valid_date(tool: str, value: Any, key: str = "date") -> ToolResult | None:
    if not isinstance(value, str) or not DATE_RE.fullmatch(value):
        return ToolResult.failure(
            ErrorCodes.INVALID_DATE,
            f"{tool}: {key} must be 'YYYY-MM-DD', got {value!r}",
        )
    try:
        from app.clinic import parse_date

        parse_date(value)
    except ValueError as exc:
        return ToolResult.failure(ErrorCodes.INVALID_DATE, f"{tool}: {exc}")
    return None


def valid_time(tool: str, value: Any, key: str) -> ToolResult | None:
    if not isinstance(value, str) or not TIME_RE.fullmatch(value):
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            f"{tool}: {key} must be 'HH:MM', got {value!r}",
        )
    hours, minutes = value.split(":")
    if not (0 <= int(hours) <= 23 and 0 <= int(minutes) <= 59):
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT, f"{tool}: {key} out of range: {value!r}"
        )
    return None


def valid_string(tool: str, value: Any, key: str, code: str = ErrorCodes.INVALID_ARGUMENT) -> ToolResult | None:
    if not isinstance(value, str) or not value.strip():
        return ToolResult.failure(
            code, f"{tool}: {key} must be a non-empty string, got {value!r}"
        )
    return None
