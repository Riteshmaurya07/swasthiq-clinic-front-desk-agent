"""Specific, structured tool errors.

The tool layer never raises bare exceptions toward the orchestrator: failures
are returned as ToolResult(error=ToolError(...)) with a machine-readable code
and an actionable message, so no tool failure can become an uncontrolled 500.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolError:
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ErrorCodes:
    INVALID_DATE = "invalid_date"
    INVALID_ARGUMENT = "invalid_argument"
    MISSING_ARGUMENT = "missing_argument"
    UNKNOWN_DOCTOR = "unknown_doctor"
    UNKNOWN_PATIENT = "unknown_patient"
    UNKNOWN_APPOINTMENT = "unknown_appointment"
    AMBIGUOUS_PATIENT = "ambiguous_patient"
    SLOT_UNAVAILABLE = "slot_unavailable"
    APPOINTMENT_CONFLICT = "appointment_conflict"
    UNAUTHORIZED = "unauthorized"
    INVALID_ESCALATION_REASON = "invalid_escalation_reason"


@dataclass
class ToolResult:
    """Uniform tool outcome: ok data or a structured error, never both."""

    ok: bool
    data: dict[str, Any] | None = None
    error: ToolError | None = None

    @classmethod
    def success(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(ok=True, data=data)

    @classmethod
    def failure(cls, code: str, message: str, **details: Any) -> "ToolResult":
        return cls(ok=False, error=ToolError(code=code, message=message, details=details))
