from __future__ import annotations

from app.errors import ErrorCodes
from app.tools import search_slots
from tests.conftest import FRIDAY_HOLIDAY, RAO_LEAVE_DAY, SETHI_LEAVE_DAY, SUNDAY, THURSDAY


def test_valid_search_returns_free_slots(clinic):
    result = search_slots(clinic, {"doctor_id": "dr_rao", "date": THURSDAY})
    assert result.ok
    assert "09:00" in result.data["slots"]
    assert "09:30" not in result.data["slots"]  # booked


def test_holiday(clinic):
    result = search_slots(clinic, {"doctor_id": "dr_rao", "date": FRIDAY_HOLIDAY})
    assert result.ok and result.data["slots"] == []


def test_doctor_leave(clinic):
    assert search_slots(clinic, {"doctor_id": "dr_sethi", "date": SETHI_LEAVE_DAY}).data["slots"] == []
    assert search_slots(clinic, {"doctor_id": "dr_rao", "date": RAO_LEAVE_DAY}).data["slots"] == []


def test_no_working_window(clinic):
    result = search_slots(clinic, {"doctor_id": "dr_rao", "date": SUNDAY})
    assert result.ok and result.data["slots"] == []


def test_booked_slot_excluded(clinic):
    result = search_slots(clinic, {"doctor_id": "dr_sethi", "date": "2026-10-08"})
    assert "10:00" not in result.data["slots"]
    assert "10:15" in result.data["slots"]


def test_deterministic_ordering(clinic):
    a = search_slots(clinic, {"doctor_id": "dr_rao", "date": THURSDAY}).data["slots"]
    b = search_slots(clinic, {"doctor_id": "dr_rao", "date": THURSDAY}).data["slots"]
    assert a == sorted(a) and a == b


def test_unknown_doctor(clinic):
    result = search_slots(clinic, {"doctor_id": "dr_x", "date": THURSDAY})
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_DOCTOR
    assert "dr_rao" in result.error.details["known_doctors"]


def test_malformed_arguments(clinic):
    bad_cases = [
        None,
        "not a dict",
        {},
        {"doctor_id": "dr_rao"},  # missing date
        {"date": THURSDAY},  # missing doctor_id
        {"doctor_id": "dr_rao", "date": "2026-10-1"},
        {"doctor_id": "dr_rao", "date": "2026/10/01"},
        {"doctor_id": "", "date": THURSDAY},
        {"doctor_id": 42, "date": THURSDAY},
    ]
    for args in bad_cases:
        result = search_slots(clinic, args)
        assert not result.ok, f"expected failure for {args!r}"
        assert result.error.code in {
            ErrorCodes.INVALID_ARGUMENT,
            ErrorCodes.MISSING_ARGUMENT,
            ErrorCodes.INVALID_DATE,
        }, f"{args!r}: {result.error}"
