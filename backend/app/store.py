"""In-memory appointment store with slot-conflict protection.

Every mutation (book / move / cancel) runs inside a threading.Lock, and the
slot-occupancy check happens INSIDE that lock at mutation time. This is what
makes double-booking impossible even when two callers race, and even when the
agent never called search_slots first.

The store starts as a copy of clinic.json's appointments and never writes back
to any file. IDs continue the shipped ap_ sequence deterministically.
"""

from __future__ import annotations

import re
import threading
from typing import Any

from app.errors import ErrorCodes, ToolResult


def _to_minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def _to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


class AppointmentStore:
    def __init__(self, clinic):
        self._lock = threading.Lock()
        self._next_seq = 1 + max(
            (int(a.id.split("_")[1]) for a in clinic.appointments if a.id.startswith("ap_")),
            default=0,
        )
        self._appointments: dict[str, dict[str, Any]] = {
            a.id: {
                "id": a.id,
                "patient_id": a.patient_id,
                "doctor_id": a.doctor_id,
                "date": a.date,
                "start": a.start,
                "end": a.end,
                "status": a.status,
            }
            for a in clinic.appointments
        }
        self._escalations: list[dict[str, Any]] = []

    # ------------------------------------------------------------- reads

    def get_appointment(self, appointment_id: str) -> dict[str, Any] | None:
        with self._lock:
            data = self._appointments.get(appointment_id)
            return dict(data) if data else None

    def all_appointments(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(a) for a in self._appointments.values()]

    def escalations(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(e) for e in self._escalations]

    # ------------------------------------------------------------- internals (lock held)

    def _conflict(self, doctor_id: str, date: str, start: str, exclude_id: str | None) -> bool:
        s = _to_minutes(start)
        e = s + 15
        for a in self._appointments.values():
            if a["id"] == exclude_id or a["status"] != "booked":
                continue
            if a["doctor_id"] != doctor_id or a["date"] != date:
                continue
            if _to_minutes(a["start"]) < e and s < _to_minutes(a["end"]):
                return True
        return False

    def _slot_in_windows(self, start: int, end: int, windows, slot_minutes: int) -> bool:
        # Slots must sit on the clinic's grid (:00/:15/:30/:45 for 15 minutes).
        if start % slot_minutes != 0:
            return False
        return any(w_start <= start and end <= w_end for w_start, w_end in windows)

    def _next_id(self) -> str:
        appointment_id = f"ap_{self._next_seq:04d}"
        self._next_seq += 1
        return appointment_id

    # ------------------------------------------------------------- mutations

    def book(
        self,
        patient_id: str,
        doctor_id: str,
        date: str,
        start: str,
        slot_minutes: int,
        weekday_windows,
    ) -> ToolResult:
        s = _to_minutes(start)
        e = s + slot_minutes
        with self._lock:
            if not self._slot_in_windows(s, e, weekday_windows, slot_minutes):
                return ToolResult.failure(
                    ErrorCodes.SLOT_UNAVAILABLE,
                    f"book_appointment: {start} on {date} is not a slot "
                    f"{doctor_id} offers (window/alignment mismatch)",
                )
            if self._conflict(doctor_id, date, start, exclude_id=None):
                return ToolResult.failure(
                    ErrorCodes.APPOINTMENT_CONFLICT,
                    f"book_appointment: slot {start} on {date} for {doctor_id} "
                    "is already booked",
                )
            appointment_id = self._next_id()
            self._appointments[appointment_id] = {
                "id": appointment_id,
                "patient_id": patient_id,
                "doctor_id": doctor_id,
                "date": date,
                "start": start,
                "end": _to_hhmm(e),
                "status": "booked",
            }
        return ToolResult.success({"appointment_id": appointment_id, "status": "booked"})

    def move(
        self,
        appointment_id: str,
        doctor_id: str,
        date: str,
        start: str,
        slot_minutes: int,
        weekday_windows,
    ) -> ToolResult:
        s = _to_minutes(start)
        e = s + slot_minutes
        with self._lock:
            current = self._appointments.get(appointment_id)
            if current is None or current["status"] != "booked":
                return ToolResult.failure(
                    ErrorCodes.UNKNOWN_APPOINTMENT,
                    f"reschedule_appointment: appointment {appointment_id!r} is "
                    "missing or not active",
                )
            original = dict(current)
            if not self._slot_in_windows(s, e, weekday_windows, slot_minutes):
                return ToolResult.failure(
                    ErrorCodes.SLOT_UNAVAILABLE,
                    f"reschedule_appointment: {start} on {date} is not a slot "
                    f"{doctor_id} offers",
                )
            if self._conflict(doctor_id, date, start, exclude_id=appointment_id):
                return ToolResult.failure(
                    ErrorCodes.APPOINTMENT_CONFLICT,
                    f"reschedule_appointment: slot {start} on {date} is already booked",
                )
            current["date"] = date
            current["start"] = start
            current["end"] = _to_hhmm(e)
        return ToolResult.success(
            {"appointment_id": appointment_id, "from": {"date": original["date"], "start": original["start"]}, "to": {"date": date, "start": start}}
        )

    def cancel(self, appointment_id: str) -> ToolResult:
        with self._lock:
            current = self._appointments.get(appointment_id)
            if current is None or current["status"] != "booked":
                return ToolResult.failure(
                    ErrorCodes.UNKNOWN_APPOINTMENT,
                    f"cancel_appointment: appointment {appointment_id!r} is "
                    "missing or not active",
                )
            current["status"] = "cancelled"
        return ToolResult.success({"appointment_id": appointment_id, "status": "cancelled"})

    def create_escalation(
        self,
        reason: str,
        conversation_id: str | None = None,
        patient_id: str | None = None,
        summary: str | None = None,
    ) -> ToolResult:
        with self._lock:
            self._escalations.append(
                {
                    "reason": reason,
                    "conversation_id": conversation_id,
                    "patient_id": patient_id,
                    "summary": summary,
                }
            )
        return ToolResult.success({"escalated": True, "reason": reason})
