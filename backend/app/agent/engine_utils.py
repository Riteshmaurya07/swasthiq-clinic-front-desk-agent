"""Small pure helpers shared by the conversation engine."""

from __future__ import annotations


def first_name_matches_count(clinic, name: str) -> int:
    """How many patients share the FIRST name token of `name`.

    Used only for ambiguity detection: 2+ matches means the identity is
    ambiguous and must never be silently resolved.
    """
    tokens = name.replace(".", " ").split()
    if not tokens:
        return 0
    first = tokens[0].lower()
    return sum(
        1
        for p in clinic.patients
        if p.name.replace(".", " ").split() and p.name.replace(".", " ").split()[0].lower() == first
    )
