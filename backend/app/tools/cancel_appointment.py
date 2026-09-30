"""cancel_appointment: cancel an existing appointment (single, never bulk).

Authorization is enforced at the tool boundary: the caller must identify a
patient_id that owns the appointment or is a listed guardian of the owner.
Knowing a name is not authorization — authorization is expressed by passing
the verified actor's patient_id as the subject of the action.
"""

from __future__ import annotations

from typing import Any

from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_string
from app.tools.identity import guardian_relationship


def cancel_appointment(clinic, store, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "cancel_appointment")) or (
        err := require_keys(args, "cancel_appointment", "appointment_id", "patient_id")
    ):
        return err
    for key, code in (
        ("appointment_id", ErrorCodes.UNKNOWN_APPOINTMENT),
        ("patient_id", ErrorCodes.UNKNOWN_PATIENT),
    ):
        if (err := valid_string("cancel_appointment", args[key], key, code)):
            return err

    appointment_id, patient_id = args["appointment_id"], args["patient_id"]

    appointment = store.get_appointment(appointment_id) or (
        {"status": "booked", "patient_id": appointment.patient_id}
        if (appointment := clinic.get_appointment(appointment_id))
        else None
    )
    if appointment is None:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_APPOINTMENT,
            f"cancel_appointment: no appointment with id {appointment_id!r}",
        )
    if appointment["status"] != "booked":
        return ToolResult.failure(
            ErrorCodes.INVALID_ARGUMENT,
            f"cancel_appointment: appointment {appointment_id!r} is "
            f"{appointment['status']!r}, not 'booked'",
        )

    owner_id = appointment["patient_id"]
    if patient_id != owner_id and not guardian_relationship(clinic, patient_id, owner_id):
        return ToolResult.failure(
            ErrorCodes.UNAUTHORIZED,
            f"cancel_appointment: patient {patient_id!r} is not authorised to "
            f"act on appointment {appointment_id!r} (belongs to {owner_id!r})",
        )

    return store.cancel(appointment_id)
