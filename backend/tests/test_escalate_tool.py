from __future__ import annotations

from app.errors import ErrorCodes
from app.tools import escalate_to_human

ALL_REASONS = ["clinical_urgent", "medical_advice", "not_authorised", "ambiguous_patient", "out_of_scope"]


def test_every_allowed_reason(clinic):
    for reason in ALL_REASONS:
        store = __import__("app.store", fromlist=["AppointmentStore"]).AppointmentStore(clinic)
        result = escalate_to_human(
            clinic,
            store,
            {"reason": reason, "conversation_id": "cv_x", "patient_id": "pt_0001", "summary": "s"},
        )
        assert result.ok, reason
        assert result.data == {"escalated": True, "reason": reason}
        assert store.escalations()[-1]["reason"] == reason


def test_invalid_reason(clinic):
    store = __import__("app.store", fromlist=["AppointmentStore"]).AppointmentStore(clinic)
    for reason in ("emergency", "CLINICAL_URGENT", "clinical"):
        result = escalate_to_human(clinic, store, {"reason": reason})
        assert not result.ok, reason
        assert result.error.code == ErrorCodes.INVALID_ESCALATION_REASON, reason
    for reason in ("", None, 42):
        result = escalate_to_human(clinic, store, {"reason": reason})
        assert not result.ok, reason
        assert result.error.code in (ErrorCodes.INVALID_ARGUMENT, ErrorCodes.MISSING_ARGUMENT), reason
    assert store.escalations() == []


def test_malformed_arguments(clinic):
    store = __import__("app.store", fromlist=["AppointmentStore"]).AppointmentStore(clinic)
    for args in (None, "clinical_urgent", {}, {"summary": "hello"}):
        result = escalate_to_human(clinic, store, args)
        assert not result.ok, args


def test_escalation_does_not_mutate_appointments(clinic):
    store = __import__("app.store", fromlist=["AppointmentStore"]).AppointmentStore(clinic)
    before = store.all_appointments()
    escalate_to_human(clinic, store, {"reason": "clinical_urgent"})
    assert store.all_appointments() == before
