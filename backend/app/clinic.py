"""Clinic domain/data layer.

Loads clinic.json and answers schedule questions with pure functions.

Rules honored here (from the assignment materials):
- Slots are 15 minutes (clinic.slot_minutes), aligned to :00/:15/:30/:45.
- Overlapping windows for a doctor are merged, never double-listed.
- A slot is available only if: the clinic is open that day (not a holiday),
  the doctor works a window that weekday, the doctor is not on leave,
  and no existing booked appointment occupies the slot.
- No system clock anywhere: every function takes an explicit date.
- No patient-identity, authorization, or conversation logic lives here.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass, field
from datetime import datetime

# Day-of-week names used by clinic.json windows.
WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

# Default clinic data. The evaluation starter pack is confidential Swasthiq
# material and is not distributed with this public repository; deployments set
# CLINIC_JSON_PATH (env var) to their own clinic file. Tests use the synthetic
# fixture in backend/tests/fixtures/clinic_fixture.json.
# Resolved lazily inside load_clinic() so the env var can be set at runtime.
CLINIC_JSON_PATH = None


def _default_clinic_path() -> pathlib.Path | None:
    env = os.environ.get("CLINIC_JSON_PATH")
    return pathlib.Path(env) if env else None


def _parse_time(value: str) -> int:
    """'09:30' -> minutes since midnight (570)."""
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)


def parse_date(value: str) -> datetime:
    """'YYYY-MM-DD' -> a date object. Raises ValueError on bad input.

    datetime is used ONLY for calendar arithmetic on explicit dates;
    it is never called without arguments, so no system clock is involved.
    """
    parts = value.split("-")
    if len(parts) != 3:
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
    year, month, day = (int(p) for p in parts)
    return datetime(year, month, day)


def date_to_string(date: datetime) -> str:
    return date.strftime("%Y-%m-%d")


def weekday_name(date: datetime) -> str:
    return WEEKDAY_NAMES[date.weekday()]


@dataclass(frozen=True)
class Doctor:
    id: str
    name: str
    speciality: str
    windows: tuple[tuple[str, int, int], ...]  # (day_name, start_min, end_min)
    leave_dates: frozenset[str]

    def windows_on(self, weekday: str) -> tuple[tuple[int, int], ...]:
        return tuple((s, e) for d, s, e in self.windows if d == weekday)


@dataclass(frozen=True)
class Patient:
    id: str
    name: str
    phone: str
    dob: str
    guardian_of: tuple[str, ...]


@dataclass(frozen=True)
class Appointment:
    id: str
    patient_id: str
    doctor_id: str
    date: str
    start: str
    end: str
    status: str


@dataclass(frozen=True)
class Clinic:
    id: str
    name: str
    city: str
    timezone: str
    slot_minutes: int
    reference_date: str
    holidays: frozenset[str]
    doctors: tuple[Doctor, ...]
    patients: tuple[Patient, ...]
    appointments: tuple[Appointment, ...]
    _doctor_index: dict[str, Doctor] = field(default_factory=dict, repr=False, compare=False)
    _patient_index: dict[str, Patient] = field(default_factory=dict, repr=False, compare=False)
    _appointment_index: dict[str, Appointment] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._doctor_index.update({d.id: d for d in self.doctors})
        self._patient_index.update({p.id: p for p in self.patients})
        self._appointment_index.update({a.id: a for a in self.appointments})

    def get_doctor(self, doctor_id: str) -> Doctor | None:
        return self._doctor_index.get(doctor_id)

    def get_patient(self, patient_id: str) -> Patient | None:
        return self._patient_index.get(patient_id)

    def get_appointment(self, appointment_id: str) -> Appointment | None:
        return self._appointment_index.get(appointment_id)


class ClinicDataUnavailable(RuntimeError):
    """Raised when no clinic data file is configured.

    The public repository ships no clinic data (the evaluation starter pack is
    confidential). Deployments point CLINIC_JSON_PATH at their own file; tests
    use the bundled synthetic fixture.
    """


def load_clinic(path: str | pathlib.Path | None = None) -> Clinic:
    """Load a clinic data file into an immutable Clinic object.

    Pure with respect to the file contents: same file, same Clinic.
    """
    file_path = pathlib.Path(path) if path is not None else _default_clinic_path()
    if file_path is None:
        raise ClinicDataUnavailable(
            "No clinic data configured. Set the CLINIC_JSON_PATH environment "
            "variable to your clinic JSON file (see README.md)."
        )
    if not file_path.exists():
        raise ClinicDataUnavailable(f"Configured clinic file not found: {file_path}")
    try:
        with file_path.open(encoding="utf-8") as handle:
            raw = json.load(handle)
    except Exception as e:
        raise ClinicDataUnavailable(f"Invalid or unreadable JSON in clinic file {file_path}: {e}")

    clinic_raw = raw["clinic"]
    doctors = tuple(
        Doctor(
            id=d["id"],
            name=d["name"],
            speciality=d["speciality"],
            windows=tuple(
                (w["day"], _parse_time(w["start"]), _parse_time(w["end"]))
                for w in d["windows"]
            ),
            leave_dates=frozenset(d.get("leave_dates", ())),
        )
        for d in raw["doctors"]
    )
    patients = tuple(
        Patient(
            id=p["id"],
            name=p["name"],
            phone=p["phone"],
            dob=p["dob"],
            guardian_of=tuple(p.get("guardian_of", ())),
        )
        for p in raw["patients"]
    )
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
        for a in raw["appointments"]
    )
    return Clinic(
        id=clinic_raw["id"],
        name=clinic_raw["name"],
        city=clinic_raw["city"],
        timezone=clinic_raw["timezone"],
        slot_minutes=clinic_raw["slot_minutes"],
        reference_date=clinic_raw["reference_date"],
        holidays=frozenset(raw.get("holidays", ())),
        doctors=doctors,
        patients=patients,
        appointments=appointments,
    )


def is_clinic_open(clinic: Clinic, date: str) -> bool:
    """The clinic is closed on listed holidays."""
    return date not in clinic.holidays


def is_doctor_available(clinic: Clinic, doctor_id: str, date: str) -> bool:
    """Doctor is scheduled that weekday, not on leave, and clinic is open."""
    doctor = clinic.get_doctor(doctor_id)
    if doctor is None:
        return False
    if not is_clinic_open(clinic, date):
        return False
    if date in doctor.leave_dates:
        return False
    return bool(doctor.windows_on(weekday_name(parse_date(date))))


def merge_windows(windows: tuple[tuple[int, int], ...]) -> list[tuple[int, int]]:
    """Merge overlapping/adjacent windows into sorted disjoint intervals.

    e.g. (09:00-12:00, 11:45-15:00) -> [(540, 900)]. Pure function.
    """
    if not windows:
        return []
    ordered = sorted(windows)
    merged = [ordered[0]]
    for start, end in ordered[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # overlaps or touches
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def _occupied_intervals(clinic: Clinic, doctor_id: str, date: str) -> list[tuple[int, int]]:
    return [
        (_parse_time(a.start), _parse_time(a.end))
        for a in clinic.appointments
        if a.doctor_id == doctor_id and a.date == date and a.status == "booked"
    ]


def get_available_slots(
    clinic: Clinic,
    doctor_id: str,
    date: str,
    slot_minutes: int | None = None,
) -> list[str]:
    """Free 15-minute start times ('HH:MM') for a doctor on a date.

    Deterministic and pure given (clinic, doctor_id, date). Returns [] when the
    clinic is closed, the doctor is on leave, or the weekday has no windows.
    Slots are aligned to the slot grid (:00/:15/:30/:45 for 15-minute slots).
    """
    step = slot_minutes if slot_minutes is not None else clinic.slot_minutes
    doctor = clinic.get_doctor(doctor_id)
    if doctor is None:
        return []
    if not is_doctor_available(clinic, doctor_id, date):
        return []

    occupied = _occupied_intervals(clinic, doctor_id, date)

    slots: list[str] = []
    for win_start, win_end in merge_windows(doctor.windows_on(weekday_name(parse_date(date)))):
        # Align slot starts to the grid relative to midnight.
        first = win_start + (-win_start % step)
        for start in range(first, win_end, step):
            end = start + step
            if end > win_end:
                continue
            if any(o_start < end and start < o_end for o_start, o_end in occupied):
                continue
            slots.append(f"{start // 60:02d}:{start % 60:02d}")
    return sorted(slots)


def get_appointments(clinic: Clinic, date: str | None = None, doctor_id: str | None = None) -> list[Appointment]:
    """Existing appointments, optionally filtered by date and/or doctor."""
    result = [
        a
        for a in clinic.appointments
        if (date is None or a.date == date) and (doctor_id is None or a.doctor_id == doctor_id)
    ]
    return sorted(result, key=lambda a: (a.date, a.start))
