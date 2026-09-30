"""reschedule_appointment: move an existing appointment to a new free slot.

Atomic: the store performs the move under its lock and rolls back on any
failure, so a failed reschedule never leaves a half-moved appointment.
"""

from __future__ import annotations

from typing import Any

from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_date, valid_string, valid_time
from app.tools.book_appointment import _merged_windows


def reschedule_appointment(clinic, store, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "reschedule_appointment")) or (
        err := require_keys(
            args, "reschedule_appointment", "appointment_id", "patient_id", "date", "start"
        )
    ):
        return err
    for key, code in (
        ("appointment_id", ErrorCodes.UNKNOWN_APPOINTMENT),
        ("patient_id", ErrorCodes.UNKNOWN_PATIENT),
    ):
        if (err := valid_string("reschedule_appointment", args[key], key, code)):
            return err
    if (err := valid_date("reschedule_appointment", args["date"])):
        return err
    if (err := valid_time("reschedule_appointment", args["start"], "start")):
        return err

    appointment_id, patient_id = args["appointment_id"], args["patient_id"]
    date, start = args["date"], args["start"]

    appointment = clinic.get_appointment(appointment_id)
    if appointment is None:
        live = store.get_appointment(appointment_id)
        if live is None:
            return ToolResult.failure(
                ErrorCodes.UNKNOWN_APPOINTMENT,
                f"reschedule_appointment: no appointment with id {appointment_id!r}",
            )
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            f"reschedule_appointment: appointment {appointment_id!r} is "
            f"{live['status']!r}, not 'booked'",
        )
    if appointment.patient_id != patient_id:
        return ToolResult.failure(
            ErrorCodes.UNAUTHORIZED,
            f"reschedule_appointment: appointment {appointment_id!r} belongs to "
            f"{appointment.patient_id!r}, not {patient_id!r}",
        )
    if appointment.doctor_id is None:
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            "reschedule_appointment: appointment has no doctor",
        )

    return store.move(
        appointment_id=appointment_id,
        doctor_id=appointment.doctor_id,
        date=date,
        start=start,
        slot_minutes=clinic.slot_minutes,
        weekday_windows=_merged_windows(clinic, appointment.doctor_id, date),
    )
