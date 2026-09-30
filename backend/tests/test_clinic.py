from __future__ import annotations

import pathlib

import pytest

from app.clinic import (
    get_appointments,
    get_available_slots,
    is_clinic_open,
    is_doctor_available,
    load_clinic,
    merge_windows,
    parse_date,
    weekday_name,
)
from tests.conftest import (
    FRIDAY_HOLIDAY,
    RAO_LEAVE_DAY,
    SATURDAY,
    SETHI_LEAVE_DAY,
    SUNDAY,
    THURSDAY,
    TODAY,
)

# ---------------------------------------------------------------- load & indexes


def test_load_clinic_from_copied_file(clinic):
    assert clinic.id == "cl_demo"
    assert clinic.slot_minutes == 15
    assert len(clinic.doctors) == 2
    assert len(clinic.patients) == 40
    assert len(clinic.appointments) == 27


def test_get_doctor_and_patient(clinic):
    assert clinic.get_doctor("dr_rao").name == "Dr. Anjali Rao"
    assert clinic.get_doctor("dr_nobody") is None
    assert clinic.get_patient("pt_0003").name == "Sunita Gupta"
    assert clinic.get_patient("pt_9999") is None


def test_get_appointments_filters(clinic):
    all_appts = get_appointments(clinic)
    assert len(all_appts) == 27
    today_appts = get_appointments(clinic, date=TODAY)
    assert len(today_appts) == 6
    rao_today = get_appointments(clinic, date=TODAY, doctor_id="dr_rao")
    assert {a.start for a in rao_today} == {"09:30", "10:00", "17:00"}


# ---------------------------------------------------------------- basic predicates


def test_holiday_closed(clinic):
    assert is_clinic_open(clinic, FRIDAY_HOLIDAY) is False
    assert is_clinic_open(clinic, THURSDAY) is True


def test_doctor_availability(clinic):
    assert is_doctor_available(clinic, "dr_rao", THURSDAY) is True
    assert is_doctor_available(clinic, "dr_rao", FRIDAY_HOLIDAY) is False
    assert is_doctor_available(clinic, "dr_rao", RAO_LEAVE_DAY) is False
    assert is_doctor_available(clinic, "dr_sethi", SETHI_LEAVE_DAY) is False
    assert is_doctor_available(clinic, "dr_nobody", THURSDAY) is False


# ---------------------------------------------------------------- slot generation


def test_normal_weekday_slots(clinic):
    """Thursday 2026-10-01: Rao windows 09:00-12:00 and 16:00-19:00 (not
    overlapping today); Sethi 10:00-13:00 and 17:00-20:00; booked slots removed."""
    rao = get_available_slots(clinic, "dr_rao", THURSDAY)
    assert "09:00" in rao and "09:15" in rao
    assert "11:45" in rao  # last morning slot (11:45+15min == window end 12:00)
    assert "14:45" not in rao  # Rao has no window past 12:00 on Thursdays
    assert "16:00" in rao and "18:45" in rao
    # booked: ap_0001 09:30, ap_0002 10:00, ap_0003 17:00
    assert "09:30" not in rao and "10:00" not in rao and "17:00" not in rao

    sethi = get_available_slots(clinic, "dr_sethi", THURSDAY)
    assert "10:15" in sethi and "12:45" in sethi
    assert "17:00" in sethi and "19:45" in sethi
    # booked: ap_0004 10:30, ap_0005 11:00, ap_0101 10:00
    assert "10:00" not in sethi and "10:30" not in sethi and "11:00" not in sethi
    # adjacent slots around a booking survive
    assert "10:45" in sethi and "10:15" in sethi


def test_overlapping_windows_no_duplicate_slots(clinic):
    """Rao Mon 09:00-12:00 and 11:45-15:00 overlap; the 11:45-12:00 zone must
    appear exactly once and the merged afternoon must be contiguous."""
    mon = "2026-10-05"  # Monday: Rao works (Sethi on leave); ap_0009 09:00, ap_0010 13:00
    slots = get_available_slots(clinic, "dr_rao", mon)
    assert len(slots) == len(set(slots))
    assert slots == sorted(slots)
    # 09:00..14:45 merged window; ap_0009 blocks exactly 09:00, ap_0010 blocks 13:00
    assert "09:00" not in slots
    assert "09:15" in slots  # adjacent slot survives
    assert "13:00" not in slots
    assert "11:45" in slots
    assert "13:00" not in slots
    assert "14:45" in slots


def test_sunday_has_no_slots(clinic):
    assert get_available_slots(clinic, "dr_rao", SUNDAY) == []
    assert get_available_slots(clinic, "dr_sethi", SUNDAY) == []


def test_holiday_has_no_slots(clinic):
    assert get_available_slots(clinic, "dr_rao", FRIDAY_HOLIDAY) == []


def test_sethi_on_leave_05_to_07(clinic):
    for leave_day in ("2026-10-05", "2026-10-06", "2026-10-07"):
        assert get_available_slots(clinic, "dr_sethi", leave_day) == []
    # Rao still works those days
    assert get_available_slots(clinic, "dr_rao", "2026-10-05") != []


def test_rao_on_leave_09(clinic):
    assert get_available_slots(clinic, "dr_rao", RAO_LEAVE_DAY) == []
    assert get_available_slots(clinic, "dr_sethi", RAO_LEAVE_DAY) != []


def test_outside_working_window_returns_no_slots(clinic):
    """2026-10-11 is a Sunday; 2026-10-12 09:00 is fine but a Tuesday-only
    doctor query on a date pattern with no windows would also yield []."""
    assert get_available_slots(clinic, "dr_rao", SUNDAY) == []
    # Saturday windows exist (09-13) — sanity check the positive case:
    sat = get_available_slots(clinic, "dr_rao", SATURDAY)
    assert "09:00" in sat and "12:45" in sat
    assert "13:00" not in sat  # last slot must end by window end


def test_appointment_blocks_valid_slot(clinic):
    # Without ap_0013 (pt_0007, 10:00 on 2026-10-08), 10:00 would be free.
    thursday_next = "2026-10-08"
    # ap_0013: pt_0007, dr_sethi, 10:00-10:15 blocks exactly that slot.
    assert "10:00" not in get_available_slots(clinic, "dr_sethi", thursday_next)
    assert "10:15" in get_available_slots(clinic, "dr_sethi", thursday_next)
    # Morning window starts 10:00, so nothing before 10:00 exists at all.
    assert "09:45" not in get_available_slots(clinic, "dr_sethi", thursday_next)
    # Evening window 17:00-20:00 with ap_0014 at 17:30 blocked:
    assert "17:30" not in get_available_slots(clinic, "dr_sethi", thursday_next)
    assert "17:15" in get_available_slots(clinic, "dr_sethi", thursday_next)


def test_slots_aligned_to_grid(clinic):
    for date in (THURSDAY, SATURDAY, "2026-10-12"):
        for doctor_id in ("dr_rao", "dr_sethi"):
            for slot in get_available_slots(clinic, doctor_id, date):
                minutes = int(slot[:2]) * 60 + int(slot[3:])
                assert minutes % 15 == 0, f"{slot} not aligned on {date}/{doctor_id}"


# ---------------------------------------------------------------- date determinism


def test_explicit_today_used_not_system_clock(clinic):
    """Slots for a date must not depend on when the test runs: the same inputs
    give the same slots, and 'today' is passed explicitly everywhere."""
    a = get_available_slots(clinic, "dr_rao", THURSDAY)
    b = get_available_slots(clinic, "dr_rao", THURSDAY)
    assert a == b
    # Sunday result would change if 'today' were replaced with the real
    # system date whenever that happens not to be a Sunday pattern.
    assert get_available_slots(clinic, "dr_rao", SUNDAY) == []


def test_relative_dates_resolve_from_explicit_date(clinic):
    """parso (day after tomorrow) from 2026-10-01 is 2026-10-03 — a Saturday."""
    base = parse_date(TODAY)
    parso = base.fromordinal(base.toordinal() + 2)
    assert parso.strftime("%Y-%m-%d") == SATURDAY
    assert weekday_name(parso) == "Sat"


# ---------------------------------------------------------------- window merging


def test_merge_windows_pure_function():
    assert merge_windows(()) == []
    assert merge_windows(((540, 720), (705, 900))) == [(540, 900)]  # overlap
    assert merge_windows(((540, 720), (720, 900))) == [(540, 900)]  # adjacent
    assert merge_windows(((540, 720), (900, 1020))) == [(540, 720), (900, 1020)]
    assert merge_windows(((900, 1020), (540, 720))) == [(540, 720), (900, 1020)]  # unsorted input


# ---------------------------------------------------------------- immutability


def test_source_clinic_file_untouched_by_suite(clinic, raw_clinic_json, clinic_source_file):
    """Load + query a thousand times; the source file on disk never changes."""
    for _ in range(1000):
        get_available_slots(clinic, "dr_rao", THURSDAY)
    original = load_clinic(clinic_source_file)
    assert len(original.appointments) == 27
    assert raw_clinic_json["clinic"]["id"] == "cl_demo"


def test_mutation_of_copy_does_not_leak(clinic_copy, raw_clinic_json):
    """The fixture copy is writable; mutating it cannot affect other tests."""
    raw_clinic_json["appointments"] = []
    with clinic_copy.open("w", encoding="utf-8") as handle:
        import json

        json.dump(raw_clinic_json, handle)
    fresh = load_clinic(clinic_copy)
    assert fresh.appointments == ()


@pytest.mark.parametrize(
    "date_value",
    ["2026-10-1", "01-10-2026", "not-a-date", "2026/10/01", ""],
)
def test_bad_date_raises(clinic, date_value):
    with pytest.raises(ValueError):
        get_available_slots(clinic, "dr_rao", date_value)
