"""lookup_patient: resolve identifying info to candidate records.

Never picks between candidates: one match is a resolution, many is a candidate
list, none is an unknown-patient error. Identity decisions belong to the agent.
"""

from __future__ import annotations

from typing import Any

from app.errors import ErrorCodes, ToolResult
from app.tools.common import require_dict, require_keys, valid_string
from app.tools.identity import candidates_by_name, candidates_by_phone_and_name


def _summary(patient) -> dict[str, Any]:
    return {"patient_id": patient.id, "name": patient.name, "dob": patient.dob}


def lookup_patient(clinic, args: dict[str, Any] | None) -> ToolResult:
    if (err := require_dict(args, "lookup_patient")):
        return err
    if (err := require_keys(args, "lookup_patient", "name")):
        return err
    if (err := valid_string("lookup_patient", args["name"], "name")):
        return err

    name = args["name"]
    phone = args.get("phone")

    if phone is not None:
        if (err := valid_string("lookup_patient", phone, "phone")):
            return err
        matches = candidates_by_phone_and_name(clinic, phone, name)
        mode = "phone_and_name"
    else:
        matches = candidates_by_name(clinic, name)
        mode = "name_only"

    payload: dict[str, Any] = {"match_mode": mode, "candidates": [_summary(p) for p in matches]}
    if len(matches) == 1:
        payload["resolved_patient_id"] = matches[0].id
    elif len(matches) == 0:
        return ToolResult.failure(
            ErrorCodes.UNKNOWN_PATIENT,
            f"lookup_patient: no patient matches name={name!r}"
            + (f" and phone={phone!r}" if phone else ""),
            match_mode=mode,
        )
    else:
        # Multiple matches: return ALL candidates, never choose.
        payload["resolved_patient_id"] = None
        payload["message"] = (
            f"{len(matches)} patients match; caller must disambiguate "
            "(e.g. confirm phone number or date of birth)"
        )
    return ToolResult.success(payload)
