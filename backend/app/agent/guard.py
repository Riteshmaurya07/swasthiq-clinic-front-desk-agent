"""Strict validation for structured model output.

The LLM (when present) is a language-understanding component only. Its JSON
proposal is validated here against a closed schema; anything malformed,
invented, or out of policy is rejected field-by-field and the engine falls
back deterministically. This module holds no business logic and never calls
tools.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

ALLOWED_FIELDS = {
    "intent", "patient_name", "phone", "doctor", "date", "time",
    "requested_action", "part_of_day",
}
ALLOWED_INTENTS = {"book", "reschedule", "cancel", "inquire", "other"}
ALLOWED_ACTIONS = {"book", "reschedule", "cancel", "advise", "admin", "other"}

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
TIME_RE = re.compile(r"([01]?\d|2[0-3]):[0-5]\d")
PHONE_RE = re.compile(r"\d{10}")


@dataclass
class ModelProposal:
    ok: bool
    fields: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def validate_model_output(raw: Any) -> ModelProposal:
    """Validate raw model output (string or dict) into a safe proposal.

    Validation rules:
    - must parse to a JSON object (string with junk around JSON is rejected)
    - unknown fields are rejected (no invented structure)
    - intent/requested_action must be in the closed vocabulary
    - date must be YYYY-MM-DD, time HH:MM (00-23), phone 10 digits
    - any violation keeps the *valid* fields and records the errors
    """
    errors: list[str] = []
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            return ModelProposal(ok=False, errors=[f"invalid JSON: {exc}"])
    elif isinstance(raw, dict):
        parsed = raw
    else:
        return ModelProposal(ok=False, errors=[f"output must be JSON object, got {type(raw).__name__}"])

    if not isinstance(parsed, dict):
        return ModelProposal(ok=False, errors=["output must be a JSON object"])

    unknown = set(parsed) - ALLOWED_FIELDS
    if unknown:
        errors.append(f"unknown field(s): {', '.join(sorted(unknown))}")

    safe: dict[str, Any] = {}

    intent = parsed.get("intent")
    if intent is not None:
        if intent in ALLOWED_INTENTS:
            safe["intent"] = intent
        else:
            errors.append(f"invalid intent {intent!r}")

    action = parsed.get("requested_action")
    if action is not None:
        if action in ALLOWED_ACTIONS:
            safe["requested_action"] = action
        else:
            errors.append(f"invalid requested_action {action!r}")

    name = parsed.get("patient_name")
    if name is not None:
        if isinstance(name, str) and 0 < len(name.strip()) <= 80:
            safe["patient_name"] = name.strip()
        else:
            errors.append(f"invalid patient_name {name!r}")

    phone = parsed.get("phone")
    if phone is not None:
        phone_digits = re.sub(r"\D", "", str(phone))
        if PHONE_RE.fullmatch(phone_digits):
            safe["phone"] = phone_digits
        else:
            errors.append(f"invalid phone {phone!r}")

    doctor = parsed.get("doctor")
    if doctor is not None:
        if isinstance(doctor, str) and re.fullmatch(r"[A-Za-z]{2,40}", doctor.strip()):
            safe["doctor"] = doctor.strip().lower()
        else:
            errors.append(f"invalid doctor {doctor!r}")

    date = parsed.get("date")
    if date is not None:
        if isinstance(date, str) and DATE_RE.fullmatch(date):
            safe["date"] = date
        else:
            errors.append(f"invalid date {date!r}")

    time = parsed.get("time")
    if time is not None:
        if isinstance(time, str) and TIME_RE.fullmatch(time):
            hour = int(time.split(":")[0])
            if 0 <= hour <= 23:
                safe["time"] = time
            else:
                errors.append(f"invalid time {time!r}")
        else:
            errors.append(f"invalid time {time!r}")

    pod = parsed.get("part_of_day")
    if pod is not None:
        if pod in {"morning", "afternoon", "evening"}:
            safe["part_of_day"] = pod
        else:
            errors.append(f"invalid part_of_day {pod!r}")

    ok = not errors
    return ModelProposal(ok=ok, fields=safe, errors=errors)
