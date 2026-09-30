"""search_slots: free slots for a doctor on a date. Read-only."""

from __future__ import annotations

from typing import Any

from app.clinic import get_available_slots
from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_date, valid_string


def search_slots(clinic, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "search_slots")) or (
        err := require_keys(args, "search_slots", "doctor_id", "date")
    ):
        return err
    doctor_id = args["doctor_id"]
    if (err := valid_string("search_slots", doctor_id, "doctor_id")):
        return err
    if (err := valid_date("search_slots", args["date"])):
        return err

    if clinic.get_doctor(doctor_id) is None:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_DOCTOR,
            f"search_slots: no doctor with id {doctor_id!r}",
            known_doctors=[d.id for d in clinic.doctors],
        )

    slots = get_available_slots(clinic, doctor_id, args["date"])
    return ToolResult.success({"doctor_id": doctor_id, "date": args["date"], "slots": slots})
