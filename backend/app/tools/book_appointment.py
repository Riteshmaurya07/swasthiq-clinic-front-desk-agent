"""book_appointment: create an appointment in a free slot.

Mutation-time conflict protection lives in AppointmentStore.book (a threading
lock plus a re-check of occupied slots inside it), so a booking is safe even
when made without a prior search_slots call, and two racers cannot both win.
"""

from __future__ import annotations

from typing import Any

from app.clinic import is_doctor_available, parse_date, weekday_name
from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_date, valid_string, valid_time


def book_appointment(clinic, store, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "book_appointment")) or (
        err := require_keys(args, "book_appointment", "patient_id", "doctor_id", "date", "start")
    ):
        return err
    for key, code in (("patient_id", ErrorCodes.UNKNOWN_PATIENT), ("doctor_id", ErrorCodes.UNKNOWN_DOCTOR)):
        if (err := valid_string("book_appointment", args[key], key, code)):
            return err
    if (err := valid_date("book_appointment", args["date"])):
        return err
    if (err := valid_time("book_appointment", args["start"], "start")):
        return err

    patient_id, doctor_id, date, start = args["patient_id"], args["doctor_id"], args["date"], args["start"]

    if clinic.get_patient(patient_id) is None:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_PATIENT,
            f"book_appointment: no patient with id {patient_id!r}",
        )
    if clinic.get_doctor(doctor_id) is None:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_DOCTOR,
            f"book_appointment: no doctor with id {doctor_id!r}",
            known_doctors=[d.id for d in clinic.doctors],
        )
    if (err := validate_bookable(clinic, doctor_id, date, "book_appointment")):
        return err

    # Store.book re-checks slot occupancy under the store lock: the conflict
    # check happens at mutation time, not search time.
    return store.book(
        patient_id=patient_id,
        doctor_id=doctor_id,
        date=date,
        start=start,
        slot_minutes=clinic.slot_minutes,
        weekday_windows=_merged_windows(clinic, doctor_id, date),
    )


def _merged_windows(clinic, doctor_id: str, date: str):
    from app.clinic import merge_windows

    doctor = clinic.get_doctor(doctor_id)
    return merge_windows(doctor.windows_on(weekday_name(parse_date(date))))


def validate_bookable(clinic, doctor_id: str, date: str, tool_name: str) -> ToolResult | None:
    """Shared date/doctor validation for booking and rescheduling tools.

    Checks: doctor exists, is available (not holiday/leave/no window),
    date is not in the past, and date is within the 30-day booking horizon.
    Returns a failure ToolResult on first violation, or None if valid.
    """
    if clinic.get_doctor(doctor_id) is None:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_DOCTOR,
            f"{tool_name}: no doctor with id {doctor_id!r}",
            known_doctors=[d.id for d in clinic.doctors],
        )
    if not is_doctor_available(clinic, doctor_id, date):
        return ToolResult.failure(
            ErrorCodes.SLOT_UNAVAILABLE,
            f"{tool_name}: {doctor_id} does not work on {date} "
            "(holiday, leave, or no working window)",
        )
    if date < clinic.reference_date:
        return ToolResult.failure(
            ErrorCodes.INVALID_DATE,
            f"{tool_name}: {date} is in the past (clinic reference date "
            f"{clinic.reference_date})",
        )
    if (parse_date(date) - parse_date(clinic.reference_date)).days > 30:
        return ToolResult.failure(
            ErrorCodes.INVALID_DATE,
            f"{tool_name}: {date} is more than 30 days ahead of the "
            f"clinic reference date {clinic.reference_date}",
        )
    return None
