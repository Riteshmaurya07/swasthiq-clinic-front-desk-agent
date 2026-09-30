from __future__ import annotations

import threading

import pytest

from app.errors import ErrorCodes
from app.store import AppointmentStore
from app.tools import book_appointment
from tests.conftest import SETHI_LEAVE_DAY, THURSDAY

RAO_THU = "2026-10-08"  # Thursday, Rao not on leave


def _free_slot(clinic, doctor_id=RAO_THU and "dr_rao", date=RAO_THU):
    from app.clinic import get_available_slots

    return get_available_slots(clinic, doctor_id, date)[0]


def test_successful_booking(clinic):
    store = AppointmentStore(clinic)
    slot = _free_slot(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU, "start": slot}
    )
    assert result.ok
    appt = store.get_appointment(result.data["appointment_id"])
    assert appt["patient_id"] == "pt_0016"
    assert appt["status"] == "booked"
    # determinism: the new id continues the fixture's max ap_NNNN sequence
    max_existing = max(int(a["id"].split("_")[1]) for a in store.all_appointments() if a["id"] != result.data["appointment_id"])
    assert int(result.data["appointment_id"].split("_")[1]) == max_existing + 1


def test_already_booked_slot_conflict(clinic):
    store = AppointmentStore(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_sethi", "date": "2026-10-08", "start": "10:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.APPOINTMENT_CONFLICT


def test_nonexistent_slot_rejected(clinic):
    store = AppointmentStore(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU, "start": "09:07"}
    )
    assert not result.ok and result.error.code == ErrorCodes.SLOT_UNAVAILABLE
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU, "start": "15:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.SLOT_UNAVAILABLE


def test_invalid_patient_and_doctor(clinic):
    store = AppointmentStore(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_9999", "doctor_id": "dr_rao", "date": RAO_THU, "start": "09:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_PATIENT
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_x", "date": RAO_THU, "start": "09:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_DOCTOR


def test_doctor_unavailable_dates(clinic):
    store = AppointmentStore(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_sethi", "date": SETHI_LEAVE_DAY, "start": "10:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.SLOT_UNAVAILABLE


def test_past_date_rejected(clinic):
    store = AppointmentStore(clinic)
    result = book_appointment(
        clinic, store, {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": "2026-09-30", "start": "09:00"}
    )
    assert not result.ok and result.error.code == ErrorCodes.INVALID_DATE


def test_malformed_arguments(clinic):
    store = AppointmentStore(clinic)
    bad = [
        None,
        [],
        {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU},  # no start
        {"patient_id": None, "doctor_id": "dr_rao", "date": RAO_THU, "start": "09:00"},
        {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": "bad", "start": "09:00"},
        {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU, "start": "9am"},
    ]
    for args in bad:
        result = book_appointment(clinic, store, args)
        assert not result.ok, f"expected failure for {args!r}"


def test_concurrent_same_slot_exactly_one_winner(clinic):
    """The mandatory concurrency test.

    Threads hit store.book directly (no prior search_slots serialization):
    the mutation-time check inside the store lock must elect exactly one
    winner. Each thread uses its own store? No — same clinic snapshot, same
    store, as both would in one running process.
    """
    store = AppointmentStore(clinic)
    args = {"patient_id": "pt_0016", "doctor_id": "dr_rao", "date": RAO_THU, "start": "09:15"}
    results: list = []
    barrier = threading.Barrier(2)

    def racer():
        barrier.wait()  # release both threads at the same instant
        results.append(book_appointment(clinic, store, dict(args)))

    threads = [threading.Thread(target=racer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    winners = [r for r in results if r.ok]
    losers = [r for r in results if not r.ok]
    assert len(winners) == 1, f"expected 1 winner, got {len(winners)}: {results}"
    assert len(losers) == 1
    assert losers[0].error.code == ErrorCodes.APPOINTMENT_CONFLICT
    booked = [
        a for a in store.all_appointments()
        if a["doctor_id"] == "dr_rao" and a["date"] == RAO_THU and a["start"] == "09:15" and a["status"] == "booked"
    ]
    assert len(booked) == 1
