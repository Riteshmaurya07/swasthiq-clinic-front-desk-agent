"""reschedule_appointment: move an existing appointment to a new free slot.

Atomic: the store performs the move under its lock and rolls back on any
failure, so a failed reschedule never leaves a half-moved appointment.
"""

from __future__ import annotations

from typing import Any

from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_date, valid_string, valid_time
from app.tools.book_appointment import _merged_windows, validate_bookable
from app.tools.identity import guardian_relationship


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

    # Check live store first (C-3)
    live = store.get_appointment(appointment_id)
    if live is not None:
        if live["status"] != "booked":
            return ToolResult.failure(
                ErrorCodes.INVALID_ARGUMENT,
                f"reschedule_appointment: appointment {appointment_id!r} is "
                f"{live['status']!r}, not 'booked'",
            )
        # Determine owner and doctor from live state
        owner_id = live["patient_id"]
        doctor_id_live = live["doctor_id"]
    else:
        # Fall back to clinic fixture
        appointment = clinic.get_appointment(appointment_id)
        if appointment is None:
            return ToolResult.failure(
                ErrorCodes.UNKNOWN_APPOINTMENT,
                f"reschedule_appointment: no appointment with id {appointment_id!r}",
            )
        if appointment.status != "booked":
            return ToolResult.failure(
                ErrorCodes.INVALID_ARGUMENT,
                f"reschedule_appointment: appointment {appointment_id!r} is "
                f"{appointment.status!r}, not 'booked'",
            )
        owner_id = appointment.patient_id
        doctor_id_live = appointment.doctor_id

    if doctor_id_live is None:
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            "reschedule_appointment: appointment has no doctor",
        )

    # Authorization: allow owner or guardian (C-2)
    if patient_id != owner_id and not guardian_relationship(clinic, patient_id, owner_id):
        return ToolResult.failure(
            ErrorCodes.UNAUTHORIZED,
            f"reschedule_appointment: appointment {appointment_id!r} belongs to "
            f"{owner_id!r}, not {patient_id!r}",
        )

    # C-4: shared booking date/availability validation
    if (err := validate_bookable(clinic, doctor_id_live, date, "reschedule_appointment")):
        return err

    return store.move(
        appointment_id=appointment_id,
        doctor_id=doctor_id_live,
        date=date,
        start=start,
        slot_minutes=clinic.slot_minutes,
        weekday_windows=_merged_windows(clinic, doctor_id_live, date),
    )
