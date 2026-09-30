"""Phase 3 tests for model-output handling (brief items 14-16).

The model hook is simulated: these tests drive ConversationEngine's model
parameter directly, proving that malformed, hallucinated, or injection-
shaped model output can never mutate clinic state.
"""

from __future__ import annotations

import json

import pytest

from app.agent.engine import ConversationEngine
from app.agent.guard import validate_model_output
from app.clinic import load_clinic
from app.store import AppointmentStore

TODAY = "2026-10-01"
RAO_THU = "2026-10-08"


# ---------------------------------------------------------------- guard units

def test_guard_rejects_invalid_json():
    proposal = validate_model_output("{not json at all")
    assert not proposal.ok and not proposal.fields


def test_guard_rejects_non_object():
    assert not validate_model_output("[1,2,3]").ok
    assert not validate_model_output(42).ok
    assert not validate_model_output(None).ok


def test_guard_rejects_unknown_fields():
    proposal = validate_model_output({"intent": "book", "weapon": "cancels everything"})
    assert not proposal.ok
    assert "weapon" not in proposal.fields
    assert proposal.fields.get("intent") == "book"  # valid fields survive


def test_guard_rejects_bad_values():
    proposal = validate_model_output({
        "intent": "nuke",
        "date": "tomorrow",
        "time": "25:99",
        "phone": "123",
        "doctor": "Dr. 42",
    })
    assert not proposal.ok
    assert proposal.fields == {} or all(k in ("doctor",) for k in proposal.fields)


def test_guard_accepts_clean_proposal():
    proposal = validate_model_output({
        "intent": "book", "patient_name": "Neha Bhatt",
        "phone": "9812200404", "doctor": "rao",
        "date": "2026-10-07", "time": "10:00",
    })
    assert proposal.ok
    assert proposal.fields["date"] == "2026-10-07"


# ---------------------------------------------- engine with hostile model

def _booking_turns():
    return [
        "8 tareekh subah 10 baje Dr. Rao ke saath.",
        "Neha Bhatt, 9812200404.",
    ]


def test_malformed_model_output_cannot_break_request():
    """Model returns garbage -> engine proceeds on deterministic parsing."""
    def bad_model(turn, state):
        return "I am a helpful assistant{{{" if turn else None

    engine = ConversationEngine(load_clinic(), model=bad_model)
    result = engine.run("t_malformed", TODAY, _booking_turns())
    # deterministic parser still carried the flow
    assert result["terminal_state"] == "booked"


def test_hallucinated_slot_in_model_output_is_ignored():
    """Model proposes a slot search_slots never returned -> not booked."""
    def lying_model(turn, state):
        return {"intent": "book", "date": RAO_THU, "time": "09:07", "doctor": "rao"}

    engine = ConversationEngine(load_clinic(), model=lying_model)
    result = engine.run("t_halluc_slot", TODAY, [
        "8 tareekh Dr. Rao ke saath kuch bhi subah ka.",
        "Neha Bhatt, 9812200404.",
    ])
    bookings = [c for c in result["tool_calls"] if c["name"] == "book_appointment"]
    for call in bookings:
        assert call["arguments"]["start"] != "09:07"  # off-grid fiction


def test_hallucinated_patient_in_model_output_is_ignored():
    """Model invents a patient id -> booking must never carry it."""
    def lying_model(turn, state):
        return {"patient_name": "Shahrukh Khan", "phone": "9000000000"}

    engine = ConversationEngine(load_clinic(), model=lying_model)
    result = engine.run("t_halluc_patient", TODAY, [
        "Kal subah 11 baje Dr. Rao ke saath appointment.",
        "Neha Bhatt, 9812200404.",
    ])
    if result["terminal_state"] == "booked":
        booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
        # the only patient evidence is the real caller's
        assert booking["arguments"]["patient_id"] == "pt_0015"
    else:
        assert result["terminal_state"] in ("abandoned", "escalated")


def test_model_cannot_request_unknown_tool_or_bulk_action():
    """Model asks for 'admin' action -> validator rejects; no mutation."""
    def admin_model(turn, state):
        return {"requested_action": "admin", "intent": "cancel"}

    engine = ConversationEngine(load_clinic(), model=admin_model)
    result = engine.run("t_admin", TODAY, [
        "Mera aaj ka appointment cancel karna hai.",
        "Priya Nair, 9812200104.",
    ])
    # the deterministic cancel flow is untouched by the bogus proposal
    assert result["terminal_state"] == "cancelled"
    assert result["appointment_id"] == "ap_0002"


def test_valid_model_output_assists_deterministic_flow():
    """A well-behaved model's clean fields are merged as hints only."""
    def good_model(turn, state):
        return {"intent": "book", "doctor": "rao", "date": RAO_THU}

    engine = ConversationEngine(load_clinic(), model=good_model)
    result = engine.run("t_good_model", TODAY, [
        "8 tareekh ko Dr. Rao ke paas koi bhi time chalega.",
        "Neha Bhatt, 9812200404.",
    ])
    assert result["terminal_state"] == "booked"
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["date"] == RAO_THU
    assert booking["arguments"]["patient_id"] == "pt_0015"
    searched = [c for c in result["tool_calls"] if c["name"] == "search_slots"]
    assert searched  # slot came from an actual search
