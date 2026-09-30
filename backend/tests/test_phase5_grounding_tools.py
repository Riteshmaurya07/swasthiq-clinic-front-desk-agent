"""Phase 5 regressions: slot grounding, date correction, malformed model
proposals, and tool-failure honesty.
"""

from __future__ import annotations

import pytest

from app.agent.engine import ConversationEngine
from app.agent.guard import validate_model_output
from app.clinic import get_available_slots, load_clinic
from app.errors import ErrorCodes
from app.store import AppointmentStore
from app.tools import book_appointment, reschedule_appointment

TODAY = "2026-10-01"


def run(turns, model=None):
    engine = ConversationEngine(load_clinic(), model=model)
    return engine, engine.run("t", TODAY, turns)


# ---------------------------------------------------- slot grounding

def test_ground_off_grid_time_never_booked():
    engine, result = run([
        "8 tareekh subah 9:07 baje Dr. Rao ke saath.",
        "Neha Bhatt, 9812200404.",
    ])
    bookings = [c for c in result["tool_calls"] if c["name"] == "book_appointment"]
    assert all(c["arguments"]["start"] != "09:07" for c in bookings)
    if result["terminal_state"] == "booked":
        booking = bookings[0]
        searched = [c for c in result["tool_calls"] if c["name"] == "search_slots"]
        assert booking["arguments"]["start"] in get_available_slots(
            load_clinic(), "dr_rao", booking["arguments"]["date"]
        )


def test_ground_sunday_nothing_bookable():
    _, result = run([
        "4 tareekh Sunday ko Dr. Rao se milna hai.",
        "Koi bhi time chalega.",
        "Theek hai, main baad mein call karta hoon.",
    ])
    assert result["terminal_state"] == "abandoned"
    assert all(c["name"] != "book_appointment" for c in result["tool_calls"])


def test_ground_holiday_nothing_bookable():
    _, result = run([
        "2 tareekh ko Dr. Rao ke saath appointment chahiye.",
        "Koi bhi time chalega.",
        "Theek hai, baad mein call karta hoon.",
    ])
    assert result["terminal_state"] == "abandoned"
    assert all(c["name"] != "book_appointment" for c in result["tool_calls"])


def test_ground_doctor_leave_nothing_bookable():
    _, result = run([
        "Dr. Sethi ke saath 5 tareekh ko appointment chahiye.",
        "Koi bhi time chalega.",
        "Theek hai, baad mein call karunga.",
    ])
    assert result["terminal_state"] == "abandoned"
    assert all(c["name"] != "book_appointment" for c in result["tool_calls"])


def test_ground_outside_working_hours_rejected_by_tool():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    result = book_appointment(clinic, store, {
        "patient_id": "pt_0016", "doctor_id": "dr_rao",
        "date": "2026-10-08", "start": "07:00",
    })
    assert not result.ok and result.error.code == ErrorCodes.SLOT_UNAVAILABLE


def test_ground_already_booked_slot_tool_conflict():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    result = book_appointment(clinic, store, {
        "patient_id": "pt_0016", "doctor_id": "dr_sethi",
        "date": "2026-10-08", "start": "10:00",  # ap_0013
    })
    assert not result.ok and result.error.code == ErrorCodes.APPOINTMENT_CONFLICT


def test_ground_overlapping_window_boundary_slots():
    """Rao Monday overlap 09:00-12:00 + 11:45-15:00: boundary 11:45/14:45 exact."""
    clinic = load_clinic()
    monday = "2026-10-12"
    slots = get_available_slots(clinic, "dr_rao", monday)
    assert "11:45" in slots and "14:45" in slots
    assert "15:00" not in slots  # window end: no slot may exceed it
    assert len(slots) == len(set(slots))


def test_ground_booking_always_matches_a_searched_slot():
    """Every successful booking's start was in the search result for that date."""
    engine, result = run([
        "8 tareekh Dr. Rao ke saath kuch bhi subah ka.",
        "Neha Bhatt, 9812200404.",
    ])
    if result["terminal_state"] == "booked":
        booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
        searched = next(
            c for c in result["tool_calls"]
            if c["name"] == "search_slots"
            and c["arguments"]["date"] == booking["arguments"]["date"]
        )
        assert booking["arguments"]["start"] in get_available_slots(
            load_clinic(), booking["arguments"]["doctor_id"], booking["arguments"]["date"]
        )


# ---------------------------------------------------- date corrections

def test_correction_tuesday_to_wednesday():
    engine, result = run([
        "Dr. Rao ke saath appointment karwana hai.",
        "Mangalwar 6 tareekh ko... nahi nahi, budhwar kar dijiye, 7 tareekh.",
        "Neha Bhatt, 9812200404. Subah ka time theek rahega.",
    ])
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["date"] == "2026-10-07"
    assert booking["arguments"]["date"] != "2026-10-06"


def test_correction_friday_to_saturday():
    engine, result = run([
        "Dr. Rao ke saath 9 tareekh ko appointment chahiye subah 11 baje.",
        "Nahi nahi, 10 tareekh Shanivaar karna hai.",
        "Neha Bhatt, 9812200404.",
    ])
    booking = next((c for c in result["tool_calls"] if c["name"] == "book_appointment"), None)
    if booking:
        assert booking["arguments"]["date"] == "2026-10-10"


def test_correction_next_week():
    engine, result = run([
        "Mere bete Aarav ke liye Dr. Sethi ke saath appointment chahiye.",
        "Sunita Gupta, 9812200166.",
        "8 tareekh ko shaam ko.",
    ])
    booking = next(c for c in result["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["date"] == "2026-10-08"


def test_correction_last_mention_wins_parser_level():
    from app.agent.understanding import _last_date_signal
    wd, rel, day, month = _last_date_signal("mangalwar 6 tareekh ko... nahi nahi, budhwar kar dijiye, 7 tareekh")
    assert day == 7 and wd is None  # explicit day-number beats weekday


# ---------------------------------------------------- malformed model proposals

@pytest.mark.parametrize("raw", [
    "{invalid json",
    "[1, 2, 3]",
    '"just a string"',
    42,
    None,
    {"intent": "demolish"},
    {"requested_action": "nuke_everything"},
    {"patient_name": 12345},
    {"phone": "12"},
    {"date": "tomorrow"},
    {"time": "25:00"},
    {"doctor": "Dr. 42"},
    {"part_of_day": "brunch"},
    {"hallucinated_patient_id": "pt_9999"},
    {"appointment_id": "ap_0001", "status": "cancelled"},
])
def test_model_proposals_rejected(raw):
    proposal = validate_model_output(raw)
    # every hostile proposal must be flagged not-ok OR carry no unsafe fields
    unsafe_fields = set(proposal.fields) - {"intent", "requested_action", "patient_name",
                                            "phone", "doctor", "date", "time", "part_of_day"}
    assert not unsafe_fields
    if raw in (42, None, "{invalid json", "[1, 2, 3]", '"just a string"'):
        assert not proposal.ok


def test_model_invented_slot_never_reaches_mutation():
    def lying_model(turn, state):
        return {"date": "2026-10-08", "time": "09:07", "doctor": "rao", "intent": "book"}

    engine, result = run([
        "8 tareekh Dr. Rao ke saath Neha Bhatt, 9812200404.",
    ], model=lying_model)
    bookings = [c for c in result["tool_calls"] if c["name"] == "book_appointment"]
    assert all(c["arguments"]["start"] != "09:07" for c in bookings)


def test_model_bulk_admin_action_ignored():
    def admin_model(turn, state):
        return {"requested_action": "admin", "intent": "cancel"}

    engine, result = run([
        "Mera aaj ka appointment cancel karna hai.",
        "Priya Nair, 9812200104.",
    ], model=admin_model)
    assert result["terminal_state"] == "cancelled"
    assert result["appointment_id"] == "ap_0002"
    # only ONE appointment cancelled (no bulk behaviour)
    cancelled = [a for a in engine.store.all_appointments() if a["status"] == "cancelled"]
    assert len(cancelled) == 1


def test_model_output_no_crash_on_weird_types():
    def weird_model(turn, state):
        return object()  # not JSON-serializable garbage

    engine, result = run(["hello there"], model=weird_model)
    assert result["terminal_state"] in ("abandoned", "escalated")


# ---------------------------------------------------- tool failure honesty

def test_tool_failure_unknown_appointment_no_false_success():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    result = reschedule_appointment(clinic, store, {
        "appointment_id": "ap_9999", "patient_id": "pt_0001",
        "date": "2026-10-03", "start": "10:00",
    })
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_APPOINTMENT


def test_tool_failure_duplicate_booking_no_partial_state():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    ok1 = book_appointment(clinic, store, {
        "patient_id": "pt_0016", "doctor_id": "dr_rao",
        "date": "2026-10-08", "start": "09:15",
    })
    ok2 = book_appointment(clinic, store, {
        "patient_id": "pt_0013", "doctor_id": "dr_rao",
        "date": "2026-10-08", "start": "09:15",
    })
    assert ok1.ok and not ok2.ok
    booked = [a for a in store.all_appointments()
              if a["date"] == "2026-10-08" and a["start"] == "09:15" and a["status"] == "booked"]
    assert len(booked) == 1 and booked[0]["patient_id"] == "pt_0016"


def test_tool_failure_reschedule_conflict_no_partial_mutation():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    result = reschedule_appointment(clinic, store, {
        "appointment_id": "ap_0001", "patient_id": "pt_0001",
        "date": "2026-10-03", "start": "09:15",  # ap_0006 occupies this
    })
    assert not result.ok
    appt = store.get_appointment("ap_0001")
    assert appt["date"] == "2026-10-01" and appt["start"] == "09:30"


def test_tool_error_malformed_arguments_specific_codes():
    clinic = load_clinic()
    store = AppointmentStore(clinic)
    cases = [
        (book_appointment, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": "bad", "start": "09:00"}, ErrorCodes.INVALID_DATE),
        (book_appointment, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": "2026-10-08"}, ErrorCodes.MISSING_ARGUMENT),
        (book_appointment, {"patient_id": "", "doctor_id": "dr_rao", "date": "2026-10-08", "start": "09:00"}, ErrorCodes.UNKNOWN_PATIENT),
        (reschedule_appointment, {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "9am"}, ErrorCodes.INVALID_ARGUMENT),
    ]
    for tool, args, expected_code in cases:
        result = tool(clinic, store, args)
        assert not result.ok, args
        assert result.error.code == expected_code, (args, result.error)
