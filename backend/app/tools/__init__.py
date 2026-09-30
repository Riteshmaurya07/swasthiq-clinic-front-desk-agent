"""Tool registry: the six tools, all pure LLM-free functions over clinic + store."""

from __future__ import annotations

from app.tools.book_appointment import book_appointment
from app.tools.cancel_appointment import cancel_appointment
from app.tools.escalate_to_human import escalate_to_human
from app.tools.lookup_patient import lookup_patient
from app.tools.reschedule_appointment import reschedule_appointment
from app.tools.search_slots import search_slots

__all__ = [
    "search_slots",
    "book_appointment",
    "reschedule_appointment",
    "cancel_appointment",
    "lookup_patient",
    "escalate_to_human",
]
