"""Patient identity: exact, data-grounded name matching only.

No fuzzy matching, no guesses: if the data supports more than one patient,
every candidate is returned and the caller must resolve it.
"""

from __future__ import annotations

import re

from app.clinic import Patient


def normalize_name(name: str) -> str:
    """Lowercase, collapse whitespace, strip punctuation except initials.

    'R. K. Sharma' -> 'r k sharma'; 'Harpreet  Singh' -> 'harpreet singh'.
    """
    lowered = re.sub(r"[.,'’-]", " ", name.strip().lower())
    return " ".join(lowered.split())


def tokens(name: str) -> set[str]:
    return set(normalize_name(name).split())


def initials_present(normalized: str) -> bool:
    return any(len(tok) == 1 for tok in normalized.split())


def name_matches(candidates: set[str], query: str) -> bool:
    """Exact-token-set equality on the normalized name.

    Initialisms are expanded when every single-letter token matches the first
    letter of a candidate token ('r k sharma' vs 'rajesh kumar sharma'), but
    ONLY as a full-name form, never as a partial match.
    """
    q = normalize_name(query)
    if not q:
        return False
    q_tokens = sorted(q.split())
    for cand in candidates:
        c_tokens = sorted(normalize_name(cand).split())
        if c_tokens == q_tokens:
            return True
        if initials_present(q) and len(c_tokens) == len(q_tokens) and all(
            (qt == ct) if len(qt) > 1 else ct.startswith(qt)
            for qt, ct in zip(q_tokens, c_tokens)
        ):
            return True
    return False


def candidates_by_name(clinic, query: str) -> list[Patient]:
    """All patients whose full name (or initials-expanded full name) matches."""
    return [p for p in clinic.patients if name_matches({p.name}, query)]


def candidates_by_surname(clinic, query: str) -> list[Patient]:
    """Patients whose FINAL name token equals the query's final token.

    Used only for AMBIGUITY DETECTION ('Sharma ji' with no other identity):
    it never resolves a patient — multiple hits must escalate.
    """
    q_tokens = normalize_name(query).split()
    if not q_tokens:
        return []
    surname = q_tokens[-1]
    return [
        p for p in clinic.patients
        if normalize_name(p.name).split()[-1:] == [surname]
    ]


def candidates_by_phone(clinic, phone: str) -> list[Patient]:
    """All patients sharing the exact phone number (numbers ARE shared in the data)."""
    return [p for p in clinic.patients if p.phone == phone]


def candidates_by_phone_and_name(clinic, phone: str, name: str) -> list[Patient]:
    """Phone + name: patients on that phone whose name matches the query."""
    return [p for p in clinic.patients if p.phone == phone and name_matches({p.name}, name)]


def guardian_relationship(clinic, guardian_id: str, patient_id: str) -> bool:
    """True iff guardian_id is a listed guardian of patient_id."""
    guardian = clinic.get_patient(guardian_id)
    return guardian is not None and patient_id in guardian.guardian_of
