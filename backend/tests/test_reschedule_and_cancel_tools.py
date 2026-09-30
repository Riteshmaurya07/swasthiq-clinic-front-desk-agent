from __future__ import annotations

from app.errors import ErrorCodes
from app.store import AppointmentStore
from app.tools import cancel_appointment, reschedule_appointment
from app.clinic import get_available_slots

# cv_0003's data: pt_0001 (Rajesh Kumar Sharma), ap_0001, 2026-10-01 09:30, dr_rao
# Target: Saturday 2026-10-03 subah 10:00


def test_successful_reschedule(clinic):
    store = AppointmentStore(clinic)
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "10:00"},
    )
    assert result.ok
    moved = store.get_appointment("ap_0001")
    assert moved["date"] == "2026-10-03" and moved["start"] == "10:00"
    # old slot freed, new slot occupied
    sat_rao = get_available_slots(clinic_for_store(store, clinic), "dr_rao", "2026-10-03")
    assert "10:00" not in sat_rao and "09:30" in sat_rao


def clinic_for_store(store, clinic):
    """A clinic whose appointments reflect the store's live state (test helper)."""
    from app.clinic import Appointment
    from dataclasses import replace

    live = store.all_appointments()
    appointments = tuple(
        Appointment(
            id=a["id"],
            patient_id=a["patient_id"],
            doctor_id=a["doctor_id"],
            date=a["date"],
            start=a["start"],
            end=a["end"],
            status=a["status"],
        )
        for a in live
    )
    return replace(clinic, appointments=appointments)


def test_occupied_target_slot(clinic):
    store = AppointmentStore(clinic)
    # ap_0006 (pt_0016) occupies 2026-10-03 09:15 with dr_rao.
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "09:15"},
    )
    assert not result.ok and result.error.code == ErrorCodes.APPOINTMENT_CONFLICT
    # rollback: original untouched
    assert store.get_appointment("ap_0001")["start"] == "09:30"
    assert store.get_appointment("ap_0001")["date"] == "2026-10-01"


def test_nonexistent_appointment(clinic):
    store = AppointmentStore(clinic)
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_9999", "patient_id": "pt_0001", "date": "2026-10-03", "start": "10:00"},
    )
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_APPOINTMENT


def test_wrong_patient(clinic):
    store = AppointmentStore(clinic)
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_0001", "patient_id": "pt_0002", "date": "2026-10-03", "start": "10:00"},
    )
    assert not result.ok and result.error.code == ErrorCodes.UNAUTHORIZED
    assert store.get_appointment("ap_0001")["start"] == "09:30"


def test_cancelled_appointment_cannot_be_rescheduled(clinic):
    store = AppointmentStore(clinic)
    store.cancel("ap_0001")
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "10:00"},
    )
    assert not result.ok


def test_malformed_reschedule_arguments(clinic):
    store = AppointmentStore(clinic)
    bad = [
        None,
        "x",
        {"appointment_id": "ap_0001", "patient_id": "pt_0001"},  # missing date/start
        {"appointment_id": "", "patient_id": "pt_0001", "date": "2026-10-03", "start": "10:00"},
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "25:00"},
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": 1000},
    ]
    for args in bad:
        result = reschedule_appointment(clinic, store, args)
        assert not result.ok, f"expected failure for {args!r}"


def test_reschedule_to_nonexistent_slot(clinic):
    store = AppointmentStore(clinic)
    result = reschedule_appointment(
        clinic,
        store,
        {"appointment_id": "ap_0001", "patient_id": "pt_0001", "date": "2026-10-03", "start": "09:07"},
    )
    assert not result.ok and result.error.code == ErrorCodes.SLOT_UNAVAILABLE
    assert store.get_appointment("ap_0001")["start"] == "09:30"  # intact


# ---------------------------------------------------------------- cancel


def test_successful_cancel_own_appointment(clinic):
    """cv_0004: Priya Nair cancels her own appointment (ap_0002)."""
    store = AppointmentStore(clinic)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0002", "patient_id": "pt_0004"})
    assert result.ok
    assert store.get_appointment("ap_0002")["status"] == "cancelled"


def test_guardian_can_cancel_dependents_appointment(clinic):
    """Meera Joshi (pt_0009) is a listed guardian of Kabir (pt_0031, ap_0004)."""
    store = AppointmentStore(clinic)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0004", "patient_id": "pt_0009"})
    assert result.ok


def test_wrong_patient_cannot_cancel(clinic):
    """cv_0009: neighbor Mohit Negi (pt_0020) cannot cancel Lakshmi Iyer's ap_0003."""
    store = AppointmentStore(clinic)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0003", "patient_id": "pt_0020"})
    assert not result.ok and result.error.code == ErrorCodes.UNAUTHORIZED
    assert store.get_appointment("ap_0003")["status"] == "booked"  # untouched


def test_non_guardian_parent_name_is_not_authorization(clinic):
    """Kavita Rawat shares a phone with Sanjay Rawat but is not his guardian."""
    store = AppointmentStore(clinic)
    # ap_0019 belongs to pt_0018 (Sanjay Rawat)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0019", "patient_id": "pt_0019"})
    assert not result.ok and result.error.code == ErrorCodes.UNAUTHORIZED


def test_nonexistent_appointment_cancel(clinic):
    store = AppointmentStore(clinic)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_4242", "patient_id": "pt_0004"})
    assert not result.ok and result.error.code == ErrorCodes.UNKNOWN_APPOINTMENT


def test_unknown_patient_cancel(clinic):
    store = AppointmentStore(clinic)
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0002", "patient_id": "pt_8888"})
    assert not result.ok


def test_cancel_does_not_affect_other_appointments(clinic):
    store = AppointmentStore(clinic)
    before = {a["id"]: a for a in store.all_appointments()}
    cancel_appointment(clinic, store, {"appointment_id": "ap_0002", "patient_id": "pt_0004"})
    after = {a["id"]: a for a in store.all_appointments()}
    assert len(after) == len(before)
    for appointment_id, original in before.items():
        if appointment_id == "ap_0002":
            assert after[appointment_id]["status"] == "cancelled"
        else:
            assert after[appointment_id] == original, appointment_id


def test_malformed_cancel_arguments(clinic):
    store = AppointmentStore(clinic)
    bad = [
        None,
        3,
        {"appointment_id": "ap_0002"},  # missing patient_id
        {"patient_id": "pt_0004"},  # missing appointment_id
        {"appointment_id": 1, "patient_id": "pt_0004"},
        {"appointment_id": "ap_0002", "patient_id": ""},
    ]
    for args in bad:
        result = cancel_appointment(clinic, store, args)
        assert not result.ok, f"expected failure for {args!r}"


def test_double_cancel_fails_cleanly(clinic):
    store = AppointmentStore(clinic)
    assert cancel_appointment(clinic, store, {"appointment_id": "ap_0002", "patient_id": "pt_0004"}).ok
    result = cancel_appointment(clinic, store, {"appointment_id": "ap_0002", "patient_id": "pt_0004"})
    assert not result.ok
