"""Doctor name resolution: deterministic, grounded in clinic.json."""

from __future__ import annotations


def resolve_doctor(clinic, doctor_name: str | None) -> str | None:
    """Map a spoken/extracted doctor name to a doctor id, or None.

    Accepts 'rao', 'anjali', 'dr rao', 'Dr. Rao'. Returns None for unknown
    doctors — the caller must never be told an unverified doctor exists.
    """
    if not doctor_name:
        return None
    tokens = {t for t in doctor_name.lower().replace(".", " ").split() if t not in ("dr", "doctor")}
    for doc in clinic.doctors:
        name_tokens = {t.lower() for t in doc.name.replace(".", " ").split()}
        if tokens & name_tokens:
            return doc.id
    return None
