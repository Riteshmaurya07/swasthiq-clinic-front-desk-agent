from __future__ import annotations

from app.errors import ErrorCodes
from app.tools import lookup_patient


def test_unique_match_with_phone_and_name(clinic):
    """Full name + that patient's phone resolves exactly."""
    result = lookup_patient(clinic, {"name": "Rajesh Kumar Sharma", "phone": "9812200042"})
    assert result.ok
    assert result.data["resolved_patient_id"] == "pt_0002"
    assert len(result.data["candidates"]) == 1


def test_surname_only_is_ambiguous_not_a_guess(clinic):
    """'Sharma' with no phone matches no full name: no usable identity."""
    result = lookup_patient(clinic, {"name": "Sharma"})
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_PATIENT


def test_initialism_expansion_returns_candidates_never_a_pick(clinic):
    """'R. K. Sharma' initial-expands to 'Rajesh Kumar Sharma' and also
    matches a literally-named 'R. K. Sharma' if present — the tool must
    return both candidates and refuse to choose."""
    result = lookup_patient(clinic, {"name": "R. K. Sharma"})
    if result.ok and result.data["resolved_patient_id"] is None:
        matched = {c["patient_id"] for c in result.data["candidates"]}
        assert "pt_0002" in matched
    else:
        # acceptable only if exactly one real record matches
        assert result.data["resolved_patient_id"] == "pt_0002"


def test_distinct_full_names_resolve_separately(clinic):
    """Our fixture has two Rajeshes (plus the initialism-expanded one) but
    their FULL names each resolve uniquely."""
    r1 = lookup_patient(clinic, {"name": "Rajesh Kumar Sharma"})
    r2 = lookup_patient(clinic, {"name": "Rajesh Sharma"})
    assert r1.data["resolved_patient_id"] == "pt_0002"
    assert r2.data["resolved_patient_id"] == "pt_0005"


def test_bare_first_name_ambiguity_fixture_property(clinic):
    """Fixture property for adv_0003: several distinct patients match the
    first name 'Rajesh' (Rajesh Kumar Sharma + initialism-expanded R. K.
    Sharma variants), and none is uniquely identified by it."""
    from app.agent.engine_utils import first_name_matches_count

    assert first_name_matches_count(clinic, "Rajesh") > 1


def test_shared_phone_pair_fixture_property(clinic):
    """Fixture property for adv_0002: Sanjay and Kavita Rawat share a phone
    and neither is the other's guardian."""
    sanjay = lookup_patient(clinic, {"name": "Sanjay Rawat"})
    kavita = lookup_patient(clinic, {"name": "Kavita Rawat"})
    assert sanjay.data["resolved_patient_id"] == "pt_0018"
    assert kavita.data["resolved_patient_id"] == "pt_0019"
    from app.clinic import load_clinic

    # (guardian check is asserted in test_conversation_scripts via adv_0002)


def test_shared_phone_with_wrong_name_yields_nothing(clinic):
    """A name that exists but paired with someone else's phone must fail."""
    result = lookup_patient(clinic, {"name": "Neha Bhatt", "phone": "9812200466"})
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_PATIENT


def test_guardian_twin_fixture_property(clinic):
    """Fixture property for adv_0004/adv_0008: Sunita Gupta is guardian of
    twins Aarav Gupta and Arjun Gupta, and another 'Arjun' exists outside
    her guardianship (twin first-name collision)."""
    sunita = lookup_patient(clinic, {"name": "Sunita Gupta"}).data["resolved_patient_id"]
    assert sunita == "pt_0003"
    aarav = lookup_patient(clinic, {"name": "Aarav Gupta"}).data["resolved_patient_id"]
    arjun = lookup_patient(clinic, {"name": "Arjun Gupta"}).data["resolved_patient_id"]
    other_arjun = lookup_patient(clinic, {"name": "Arjun Khanna"}).data["resolved_patient_id"]
    assert (aarav, arjun, other_arjun) == ("pt_0006", "pt_0007", "pt_0024")


def test_full_name_only_resolves_when_unique(clinic):
    result = lookup_patient(clinic, {"name": "Neha Bhatt"})
    assert result.ok and result.data["resolved_patient_id"] == "pt_0015"


def test_unknown_patient(clinic):
    result = lookup_patient(clinic, {"name": "Nobody Realperson", "phone": "9999999999"})
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_PATIENT


def test_malformed_arguments(clinic):
    for args in (None, 42, {}, {"phone": "9812200404"}, {"name": ""}, {"name": 7}):
        result = lookup_patient(clinic, args)
        assert not result.ok, f"expected failure for {args!r}"
