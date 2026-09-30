from __future__ import annotations

import pathlib

import pytest

from app.store import AppointmentStore
from app.tools import (
    book_appointment,
    cancel_appointment,
    escalate_to_human,
    lookup_patient,
    reschedule_appointment,
    search_slots,
)


def test_no_llm_imports_in_tool_layer():
    """Guarantee: no LLM client/network/AI library appears anywhere in the
    tool layer, store, errors, or clinic domain code."""
    roots = [
        pathlib.Path(__file__).resolve().parents[1] / "app" / "tools",
        pathlib.Path(__file__).resolve().parents[1] / "app" / "clinic.py",
        pathlib.Path(__file__).resolve().parents[1] / "app" / "store.py",
        pathlib.Path(__file__).resolve().parents[1] / "app" / "errors.py",
    ]
    forbidden = ("openai", "anthropic", "langchain", "requests", "httpx", "urllib")
    for root in roots:
        files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
        for path in files:
            source = path.read_text(encoding="utf-8").lower()
            for word in forbidden:
                assert f"{word}" not in source.replace(f"{word}-free", ""), f"{path.name} mentions {word!r}"


def test_full_flow_search_then_book_like_cv_0001(clinic):
    """cv_0001 shape: lookup -> search Sat -> book, all through tools."""
    store = AppointmentStore(clinic)
    identified = lookup_patient(clinic, {"name": "Harpreet Singh", "phone": "9812200311"})
    assert identified.data["resolved_patient_id"] == "pt_0013"

    slots = search_slots(clinic, {"doctor_id": "dr_rao", "date": "2026-10-03"})
    assert "09:30" in slots.data["slots"]

    booked = book_appointment(
        clinic,
        store,
        {"patient_id": "pt_0013", "doctor_id": "dr_rao", "date": "2026-10-03", "start": "09:30"},
    )
    assert booked.ok and booked.data["status"] == "booked"


def test_tools_reject_none_arguments_uniformly(clinic):
    store = AppointmentStore(clinic)
    assert not search_slots(clinic, None).ok
    assert not lookup_patient(clinic, None).ok
    assert not book_appointment(clinic, store, None).ok
    assert not reschedule_appointment(clinic, store, None).ok
    assert not cancel_appointment(clinic, store, None).ok
    assert not escalate_to_human(clinic, store, None).ok
