"""escalate_to_human: structured handoff. Never mutates clinic appointment data."""

from __future__ import annotations

from typing import Any

from app.errors import ErrorCodes, ToolResult
from app.schemas import ESCALATION_REASONS
from app.tools.common import require_dict, require_keys, valid_string


def escalate_to_human(clinic, store, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "escalate_to_human")) or (
        err := require_keys(args, "escalate_to_human", "reason")
    ):
        return err
    reason = args["reason"]
    if not isinstance(reason, str) or not reason.strip():
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            f"escalate_to_human: reason must be a non-empty string, got {reason!r}",
        )
    if reason not in ESCALATION_REASONS:
        return ToolResult.failure(
            ErrorCodes.INVALID_ESCALATION_REASON,
            f"escalate_to_human: reason {reason!r} not in {sorted(ESCALATION_REASONS)}",
        )

    return store.create_escalation(
        reason=reason,
        conversation_id=args.get("conversation_id"),
        patient_id=args.get("patient_id"),
        summary=args.get("summary"),
    )
