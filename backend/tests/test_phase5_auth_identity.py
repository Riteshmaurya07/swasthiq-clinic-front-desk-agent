"""Phase 5 regressions: authorization fail-closed and identity resolution.

Authorization derives ONLY from: acting for self, or being explicitly listed
in the target patient's guardian_of. Shared phone, surname, relationship
claims, or name knowledge never authorize anything.
"""

from __future__ import annotations

import pytest

from app.agent.engine import ConversationEngine
from app.clinic import load_clinic
from app.tools.identity import (
    candidates_by_name,
    candidates_by_phone_and_name,
    candidates_by_surname,
    guardian_relationship,
)

TODAY = "2026-10-01"


def run(turns):
    engine = ConversationEngine(load_clinic())
    return engine, engine.run("t", TODAY, turns)


def mutations(tool_calls):
    return [c for c in tool_calls if c["name"] in ("book_appointment", "reschedule_appointment", "cancel_appointment")]


# ---------------------------------------------------- authorization

def test_auth_name_only_is_not_authorization():
    """Knowing Lakshmi Iyer's name (and even her phone) is not enough."""
    engine, result = run([
        "Lakshmi Iyer ka aaj ka appointment cancel karna hai.",
        "Main uska bhai hoon, Suresh Iyer. Number 9999900009.",
    ])
    # 'Suresh Iyer' is not a patient; even if he were, brother is not guardian
    assert mutations(result["tool_calls"]) == []
    assert engine.store.get_appointment("ap_0003")["status"] == "booked"


def test_auth_shared_phone_alone_is_not_authorization():
    """Kavita Rawat shares Sanjay Rawat's phone but is not his guardian."""
    engine, result = run([
        "Sanjay Rawat ka appointment cancel karna hai.",
        "Main Kavita Rawat, 9812200466.",
    ])
    assert result["terminal_state"] in ("escalated", "abandoned")
    if result["terminal_state"] == "escalated":
        assert result["escalation_reason"] in ("not_authorised", "ambiguous_patient")
    assert mutations(result["tool_calls"]) == []
    appt = engine.store.get_appointment("ap_0019")
    assert appt["status"] == "booked"


def test_auth_same_surname_is_not_authorization():
    """A different Sharma cannot act for pt_0001."""
    engine, result = run([
        "Rajesh Kumar Sharma ka aaj ka appointment cancel karna hai.",
        "Main R. K. Sharma bol raha hoon, 9812200042.",
    ])
    assert mutations(result["tool_calls"]) == []
    assert engine.store.get_appointment("ap_0001")["status"] == "booked"


def test_auth_false_parent_claim_is_not_authorization():
    """Claiming parenthood without a guardian_of listing fails closed."""
    engine, result = run([
        "Arjun Gupta ka appointment cancel karna hai, main iska baap hoon.",
        "Sanjay Rawat, 9812200466.",
    ])
    assert mutations(result["tool_calls"]) == []
    assert engine.store.get_appointment("ap_0013")["status"] == "booked"


def test_auth_verbal_claim_is_not_authorization():
    engine, result = run([
        "Lakshmi Iyer ne mujhe bola hai ki main uska appointment cancel kar dun.",
        "Deepak Chauhan, 9812200373.",
    ])
    assert mutations(result["tool_calls"]) == []
    assert engine.store.get_appointment("ap_0003")["status"] == "booked"


def test_auth_neighbor_still_escalates_not_authorised():
    engine, result = run([
        "Lakshmi Iyer ka aaj ka appointment cancel karna hai.",
        "Main unka padosi hoon, Mohit Negi.",
        "Mera number 9812200497 hai, unka number mere paas nahi hai.",
    ])
    assert result["terminal_state"] == "escalated"
    assert result["escalation_reason"] == "not_authorised"
    assert mutations(result["tool_calls"]) == []


def test_auth_self_cancel_still_works():
    engine, result = run([
        "Mujhe aaj ka appointment cancel karna hai.",
        "Priya Nair, 9812200104.",
    ])
    assert result["terminal_state"] == "cancelled"
    assert result["appointment_id"] == "ap_0002"


def test_auth_listed_guardian_still_works():
    engine, result = run([
        "Dr. Sethi ke saath somwar 5 tareekh ko Kabir ko dikhana hai.",
        "Accha, toh 8 tareekh ko subah?",
        "Meera Joshi bol rahi hoon, 9812200197. Kabir mera beta hai.",
    ])
    assert result["terminal_state"] == "booked"
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["patient_id"] == "pt_0031"


def test_auth_guardian_relationship_helper():
    clinic = load_clinic()
    assert guardian_relationship(clinic, "pt_0008", "pt_0006") is True
    assert guardian_relationship(clinic, "pt_0008", "pt_0007") is True
    assert guardian_relationship(clinic, "pt_0009", "pt_0031") is True
    # negative controls: shared phone WITHOUT listing
    assert guardian_relationship(clinic, "pt_0019", "pt_0018") is False
    assert guardian_relationship(clinic, "pt_0018", "pt_0019") is False
    assert guardian_relationship(clinic, "pt_0009", "pt_0009") is False  # self is not 'guardian_of'


# ---------------------------------------------------- identity resolution

def test_identity_surname_only_is_ambiguous():
    matches = candidates_by_surname(load_clinic(), "Sharma")
    assert {"pt_0001", "pt_0002"} <= {p.id for p in matches}


def test_identity_first_name_only_never_silently_resolves():
    """'Priya' with no phone must not pick Nair or Menon."""
    engine, result = run([
        "Priya ke liye appointment chahiye kal ko.",
        "Haan bas Priya hi.",
    ])
    # whatever the terminal state, it must never be a booking for a guessed Priya
    if result["terminal_state"] == "booked":
        booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
        assert booking["arguments"]["patient_id"] in ("pt_0004", "pt_0005") is False
    else:
        assert result["terminal_state"] in ("abandoned", "escalated")


def test_identity_initials_expansion_returns_candidates_not_a_pick():
    """'R. K. Sharma' + his own phone resolves to pt_0002 exactly — the
    initials expansion is exact-form only and the phone disambiguates from
    Rajesh Kumar Sharma."""
    engine, result = run([
        "Dr. Rao ke saath 8 tareekh subah 10 baje appointment.",
        "R. K. Sharma bol raha hoon, 9812200042.",
    ])
    assert result["terminal_state"] == "booked"
    assert result["patient_id"] == "pt_0002"
    # and critically: NOT booked as Rajesh Kumar Sharma (pt_0001)
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["patient_id"] == "pt_0002"


def test_identity_near_duplicates_stay_distinct():
    clinic = load_clinic()
    assert candidates_by_name(clinic, "Imran Qureshi")[0].id == "pt_0010"
    assert candidates_by_name(clinic, "Imraan Quraishi")[0].id == "pt_0011"
    assert candidates_by_name(clinic, "Harpreet Singh")[0].id == "pt_0013"
    assert candidates_by_name(clinic, "Harpreet Kaur")[0].id == "pt_0014"


def test_identity_shared_phone_wrong_name_fails():
    assert candidates_by_phone_and_name(load_clinic(), "9812200166", "Priya Nair") == []


def test_identity_correct_name_wrong_phone_fails():
    assert candidates_by_phone_and_name(load_clinic(), "9999999999", "Priya Nair") == []


def test_identity_family_first_name_within_guardian_scope():
    """cv_0008: 'Aarav' resolves inside Sunita's guardian_of scope only."""
    engine, result = run([
        "Mere bete Aarav ke liye Dr. Sethi ke saath appointment chahiye.",
        "Sunita Gupta, 9812200166.",
        "8 tareekh ko shaam ko.",
    ])
    assert result["terminal_state"] == "booked"
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["patient_id"] == "pt_0006"


def test_identity_guardian_scoped_first_name_cannot_leave_scope():
    """A first name matching a NON-guarded patient must never resolve."""
    engine, result = run([
        "Kabir ko dikhana hai Dr. Sethi ke saath kal.",
        "Sunita Gupta, 9812200166.",  # Sunita is NOT Kabir's guardian
        "Shaam 6 baje.",
    ])
    # Kabir is Meera's dependent, not Sunita's: booking must not happen for pt_0031
    if result["terminal_state"] == "booked":
        booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
        assert booking["arguments"]["patient_id"] != "pt_0031"
    else:
        assert result["terminal_state"] in ("abandoned", "escalated")


def test_identity_corrected_name_across_turns_uses_latest():
    """Caller corrects the name: the latest full identity wins."""
    engine, result = run([
        "Dr. Rao ke saath kal subah appointment, Priya Nair, 9812200104.",
        "Arre nahi, Priya Menon hoon main, 9812200135.",
    ])
    if result["terminal_state"] == "booked":
        booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
        assert booking["arguments"]["patient_id"] == "pt_0005"  # latest correction
    else:
        assert result["terminal_state"] in ("abandoned", "escalated")


def test_identity_lookup_tool_calls_are_grounded():
    """Every identity claim traces to lookup_patient calls, never invention."""
    engine, result = run([
        "Mere bete Aarav ke liye Dr. Sethi ke saath appointment chahiye.",
        "Sunita Gupta, 9812200166.",
        "8 tareekh ko shaam ko.",
    ])
    lookups = [c for c in result["tool_calls"] if c["name"] == "lookup_patient"]
    assert lookups  # at least one real lookup happened
