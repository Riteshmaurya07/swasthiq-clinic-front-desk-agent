"""Conversation orchestration engine.

Pipeline per turn: understand -> safety pre-check -> deterministic state
update -> (when complete and authorized) deterministic tools -> reply.

The deterministic rule-based layer is authoritative for every safety-
critical decision: clinical escalation, advice escalation, injection
refusal, identity, authorization, and slot grounding. An LLM, when plugged
in (Phase 4+), may only *propose* structured fields which pass through
validate_model_output(); it can never execute tools or mutate state.

CV map: cv_0001 book | cv_0002 correction | cv_0003 reschedule
cv_0004 cancel | cv_0005 closed -> abandoned | cv_0006 leave+guardian book
cv_0007 ambiguous -> escalated | cv_0008 guardian book for child
cv_0009 unauthorized -> escalated | cv_0010 advice -> escalated
cv_0011 urgent mid-booking -> escalated | cv_0012 parso/gyarah -> book
cv_0013 noise -> abandoned | cv_0014 injection -> refused
cv_0015 taken slot -> alternative -> book
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from app.agent.doctor_resolver import resolve_doctor
from app.agent.guard import validate_model_output
from app.agent.state import ConversationState
from app.agent.understanding import understand
from app.clinic import get_available_slots, parse_date
from app.tools.identity import candidates_by_name, candidates_by_surname
from app.store import AppointmentStore
from app.tools import (
    book_appointment,
    cancel_appointment,
    escalate_to_human,
    lookup_patient,
    reschedule_appointment,
    search_slots,
)

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# One escalation summary per third-party authorization failure, shared by every
# action path so the same refusal always reports the same reason and wording.
TARGET_ESCALATION_SUMMARIES = {
    "ambiguous_patient": "Mentioned patient name matches more than one record",
    "not_authorised": "Caller is not authorised to act on the mentioned record",
}


def date_to_str(d) -> str:
    return d.strftime("%Y-%m-%d")


def _weekday_offset(today: str, weekday_name: str) -> int:
    base = parse_date(today)
    target = WEEKDAY_NAMES.index(weekday_name)
    delta = (target - base.weekday()) % 7
    return delta if delta > 0 else 7  # "Saturday" = the NEXT Saturday


class ConversationEngine:
    def __init__(self, clinic, store: AppointmentStore | None = None, model=None):
        self.clinic = clinic
        self.store = store if store is not None else AppointmentStore(clinic)
        # model: optional callable(turn_text, state) -> raw proposal; every
        # proposal must pass validate_model_output() before fields merge.
        self.model = model

    # ------------------------------------------------------------------ run

    def run(self, conversation_id: str, today: str, turns: list[str]) -> dict[str, Any]:
        state = ConversationState(conversation_id=conversation_id, today=today)
        for turn_index, turn in enumerate(turns):
            state.current_turn_index = turn_index
            if state.escalated:
                break  # already handed to a human; nothing may change that
            if state.finished:
                # The scheduling flow is closed, but SAFETY never is: every later
                # caller turn still passes the injection / clinical-urgency /
                # medical-advice pre-check. A completed booking must never be
                # able to silence a later emergency (C-1). The pre-check can
                # escalate or refuse, but no further mutation is ever reachable
                # here — the normal pipeline is skipped for this turn.
                self._safety_precheck(state, understand(turn))
                continue
            self._process_turn(state, turn)
        return self._finalize(state)

    # ------------------------------------------------------------------ per-turn pipeline

    def _process_turn(self, state: ConversationState, turn: str) -> None:
        signals = understand(turn)

        if self.model is not None:
            proposal = validate_model_output(self.model(turn, state))
            if proposal.ok:
                self._merge_proposal(state, proposal.fields)

        # 1. SAFETY PRE-CHECK — before identity, before any tool work
        if self._safety_precheck(state, signals):
            return

        # 2. empty/noise turn with nothing under way
        if signals.caller_disengaged and not self._has_work(state):
            state.caller_disengaged = True
            return

        # 3. identity + third-party target
        if signals.patient_name or signals.phone or signals.target_name or signals.mentions_dependent:
            self._absorb_identity(state, signals)

        # 4. request parameters (last explicit mention wins)
        self._absorb_request(state, signals)

        # 5. intent (first intent sticks unless a new one arrives explicitly)
        if signals.intent:
            state.intent = signals.intent

        # 6. act when enough validated information is present
        if not state.finished:
            self._maybe_act(state)

    def _safety_precheck(self, state: ConversationState, signals: TurnSignals) -> bool:
        """Injection / clinical-urgency / medical-advice gate.

        Runs on EVERY caller turn, including turns that arrive after a normal
        action already completed: a booked/cancelled/moved appointment must
        never be able to silence a later emergency or injection attempt (C-1).
        Returns True when the turn was consumed by safety, in which case the
        caller must not process it any further.

        An escalation or refusal here OVERRIDES a previously completed normal
        flow: the completed action is dropped from the outcome so the response
        reports the safety state instead of claiming a booking.
        """
        if signals.injection:
            self._refuse(state)
            return True
        if signals.clinical_urgent:
            self._escalate(state, "clinical_urgent",
                           summary="Caller describes symptoms needing a clinician now")
            return True
        if signals.medical_advice:
            self._escalate(state, "medical_advice",
                           summary="Caller asks for clinical judgement the desk cannot give")
            return True
        return False

    # ------------------------------------------------------------------ model proposals

    def _merge_proposal(self, state: ConversationState, fields: dict) -> None:
        """Merge a *validated* proposal as candidate hints only.

        Proposals never set/clear safety flags, never call tools, never
        introduce slots (slots come only from search_slots results).
        """
        if "patient_name" in fields and not state.actor.name:
            state.actor.name = fields["patient_name"]
        if "phone" in fields and not state.actor.phone:
            state.actor.phone = fields["phone"]
        if "doctor" in fields and not state.doctor_id:
            resolved = resolve_doctor(self.clinic, fields["doctor"])
            if resolved:
                state.doctor_id = resolved
        if "date" in fields and not state.date:
            state.date = self._resolve_date_token(state, date_str=fields["date"])
        if "time" in fields and not state.time:
            state.time = fields["time"]
        if "part_of_day" in fields and not state.part_of_day:
            state.part_of_day = fields["part_of_day"]
        if "intent" in fields and not state.intent:
            state.intent = fields["intent"]

    # ------------------------------------------------------------------ identity

    def _absorb_identity(self, state: ConversationState, signals: TurnSignals) -> None:
        if signals.patient_name:
            state.actor.name = signals.patient_name
        if signals.phone:
            state.actor.phone = signals.phone
        if signals.target_name:
            state.target_name = signals.target_name
            state.target_patient_id = None  # re-resolve on new mention
            state.target_match_count = 0
            state.existing_appointment_id = None  # the earlier target's appointment
            state.target_mentioned = True
        if signals.mentions_dependent:
            state.target_mentioned = True
        if state.actor.patient_id is None and (state.actor.name or state.actor.phone):
            self._resolve_actor(state)
        if state.target_name and state.actor.patient_id and state.target_patient_id is None:
            self._resolve_target(state)

    def _resolve_actor(self, state: ConversationState) -> None:
        args: dict[str, Any] = {"name": state.actor.name or ""}
        if state.actor.phone:
            args["phone"] = state.actor.phone
        result = lookup_patient(self.clinic, args)
        state.record_tool_call("lookup_patient", args)
        if result.ok and result.data.get("resolved_patient_id"):
            state.actor.patient_id = result.data["resolved_patient_id"]
        # multiple candidates or no match: stay unresolved; finalize decides

    def _resolve_target(self, state: ConversationState) -> None:
        """Resolve the third-party patient by name in the caller's context.

        The target must share the caller's phone (family plan) or be a
        dependent the caller is a listed guardian for. Otherwise the target
        stays unresolved and the authorization check fails closed.
        """
        result = lookup_patient(self.clinic, {"name": state.target_name})
        state.record_tool_call("lookup_patient", {"name": state.target_name})
        candidates = result.data["candidates"] if result.ok else []

        if len(candidates) != 1 and state.actor.patient_id:
            # Callers speak of dependents by first name ("mere bete Aarav ke
            # liye", "Kabir ko dikhana hai"). Resolve a FIRST-NAME match
            # among the patients the caller is a LISTED GUARDIAN for (plus
            # the caller themself) — identity resolution scoped to the
            # guardian relationship. Authorization never comes from a shared
            # phone number: the brief explicitly rules that out.
            actor = self.clinic.get_patient(state.actor.patient_id)
            if actor is not None:
                scoped = list(actor.guardian_of) + [state.actor.patient_id]
                first_token = normalize_first_name(state.target_name)
                if first_token:
                    matches = [
                        pid for pid in scoped
                        if (p := self.clinic.get_patient(pid)) is not None
                        and normalize_first_name(p.name) == first_token
                    ]
                    if len(matches) == 1:
                        candidates = [{"patient_id": matches[0]}]

        if len(candidates) != 1:
            state.target_match_count = len(candidates)
            return  # zero or several: stays unresolved; guards fail closed
        state.target_match_count = 1
        target_id = candidates[0]["patient_id"]
        target = self.clinic.get_patient(target_id)
        if target is None:
            state.target_match_count = 0
            return
        # Authorization: listed guardian only. Never "shares the caller's
        # phone" — clinic.json's Sanjay/Kavita Rawat pair shares a phone
        # with no guardian link, and the brief forbids phone-based authority.
        if guardian_check(self.clinic, state.actor.patient_id, target_id):
            state.target_patient_id = target_id
        # else: unauthorized -> guards fail closed later

    # ------------------------------------------------------------------ requests

    def _absorb_request(self, state: ConversationState, signals: TurnSignals) -> None:
        if signals.doctor_name:
            resolved = resolve_doctor(self.clinic, signals.doctor_name)
            if resolved:
                state.doctor_id = resolved

        if signals.weekday:
            state.date = self._resolve_date_token(state, weekday=signals.weekday)
        if signals.relative_date:
            state.date = self._resolve_date_token(state, relative=signals.relative_date)
        if signals.day_number is not None:
            resolved = self._resolve_date_token(
                state, day=signals.day_number, month=signals.month_number
            )
            if resolved:
                state.date = resolved

        if signals.time:
            state.time = signals.time
            if signals.part_of_day:
                state.part_of_day = signals.part_of_day
        elif signals.part_of_day:
            state.part_of_day = signals.part_of_day

        if signals.accept_any_time:
            state.accept_any_time = True

    def _resolve_date_token(
        self,
        state: ConversationState,
        date_str: str | None = None,
        weekday: str | None = None,
        relative: str | None = None,
        day: int | None = None,
        month: int | None = None,
    ) -> str | None:
        today = parse_date(state.today)
        if relative == "aaj":
            return state.today
        if relative == "kal":
            return date_to_str(today + timedelta(days=1))
        if relative == "parso":
            return date_to_str(today + timedelta(days=2))
        if weekday:
            return date_to_str(today + timedelta(days=_weekday_offset(state.today, weekday)))
        if day is not None:
            if month is not None:
                try:
                    return date_to_str(today.replace(month=month, day=day))
                except ValueError:
                    return None
            try:
                candidate = today.replace(day=day)
            except ValueError:
                return None
            if candidate < today:
                next_month = today.month + 1
                year = today.year + (1 if next_month > 12 else 0)
                try:
                    candidate = candidate.replace(year=year, month=1 if next_month > 12 else next_month)
                except ValueError:
                    return None
            return date_to_str(candidate)
        if date_str:
            return date_str
        return None

    # ------------------------------------------------------------------ action gating

    def _has_work(self, state: ConversationState) -> bool:
        return bool(state.intent or state.actor.name or state.actor.phone
                    or state.target_name)

    def _maybe_act(self, state: ConversationState) -> None:
        if state.intent == "book":
            self._try_book(state)
        elif state.intent == "reschedule":
            self._try_reschedule(state)
        elif state.intent == "cancel":
            self._try_cancel(state)

    # ------------------------------------------------------------------ booking

    def _try_book(self, state: ConversationState) -> None:
        if not (state.doctor_id and state.date):
            return
        if not state.accept_any_time and state.part_of_day is None and state.time is None:
            return

        slots = self._search(state, state.doctor_id, state.date)
        if not slots:
            return  # closed day / leave: nothing to offer (cv_0005)

        wanted = self._requested_slot(state)
        if wanted is None:
            # part-of-day only ("subah", "shaam ko") or any-time
            candidates = self._filter_by_part_of_day(slots, state.part_of_day)
            if not candidates:
                if state.accept_any_time and slots:
                    candidates = slots
                else:
                    return
            if state.actor.patient_id is None:
                return  # wait for identity before mutating
            self._book(state, state.doctor_id, state.date, candidates[0])
            return

        if wanted in slots:
            if state.actor.patient_id is None:
                return
            self._book(state, state.doctor_id, state.date, wanted)
            return

        # requested slot not in free list: mark and hold (offer in reply)
        state.requested_slot_unavailable = True

    def _requested_slot(self, state: ConversationState) -> str | None:
        if state.time is None:
            return None
        hour, minute = state.time.split(":")
        hour = int(hour)
        if state.part_of_day == "evening" and hour < 12:
            hour += 12
        elif state.part_of_day == "afternoon" and hour < 12:
            hour += 12
        return f"{hour:02d}:{minute}"

    def _filter_by_part_of_day(self, slots: list[str], part_of_day: str | None) -> list[str]:
        if not part_of_day:
            return slots
        def hour_of(s: str) -> int:
            return int(s.split(":")[0])
        if part_of_day == "morning":
            return [s for s in slots if hour_of(s) < 12]
        if part_of_day == "afternoon":
            return [s for s in slots if 12 <= hour_of(s) < 16]
        return [s for s in slots if hour_of(s) >= 16]

    def _book(self, state: ConversationState, doctor_id: str, date: str, start: str) -> None:
        target = state.target_patient_id or state.actor.patient_id
        if target is None:
            return
        if state.target_mentioned and state.target_patient_id is None:
            # A third-party patient/dependent was mentioned but never
            # resolved to a verified record. Booking for the caller instead
            # would silently act on the wrong patient: fail closed.
            return
        args = {"patient_id": target, "doctor_id": doctor_id, "date": date, "start": start}
        result = book_appointment(self.clinic, self.store, args)
        state.record_tool_call("book_appointment", args)
        if result.ok:
            state.action_done = "booked"
            state.appointment_id = result.data["appointment_id"]
            state.final_patient_id = target
            state.chosen_slot = start
        # failure: stay unfinished; finalize decides

    # ------------------------------------------------------------------ target authorization

    def _authorized_target(self, state: ConversationState) -> tuple[str | None, str | None]:
        """(subject_patient_id, escalation_reason) for the patient an action concerns.

        One rule shared by every action that can carry a third-party target:
        - a resolved target is used as-is (resolution already proved guardian authority);
        - a name matching several records is ambiguous_patient;
        - an unknown, unnamed-dependent, or unauthorized target is not_authorised.

        A third-party mention NEVER falls back to the caller's own record.
        """
        if state.target_patient_id is not None:
            return state.target_patient_id, None
        if state.target_match_count > 1:
            return None, "ambiguous_patient"
        return None, "not_authorised"

    # ------------------------------------------------------------------ reschedule

    def _try_reschedule(self, state: ConversationState) -> None:
        if state.actor.patient_id is None:
            return
        # cv_0009 parity: a mentioned third party must NEVER become the caller's
        # own appointment. Resolve WHO is being rescheduled before looking up
        # any appointment, and escalate rather than substituting the caller.
        subject = state.actor.patient_id
        if state.target_mentioned:
            subject, reason = self._authorized_target(state)
            if reason is not None:
                self._escalate(state, reason, summary=TARGET_ESCALATION_SUMMARIES[reason])
                return
        if state.existing_appointment_id is None:
            state.existing_appointment_id = self._find_appointment(state, subject)
            if state.existing_appointment_id is None:
                return
        if not state.date:
            return
        if not state.accept_any_time and state.part_of_day is None and state.time is None:
            return

        appointment = self.store.get_appointment(state.existing_appointment_id)
        if appointment is None:
            state.existing_appointment_id = None
            return

        doctor_id = appointment["doctor_id"]
        slots = self._search(state, doctor_id, state.date)
        wanted = self._requested_slot(state)

        if wanted and wanted in slots:
            self._reschedule(state, state.existing_appointment_id, doctor_id, state.date, wanted)
            return
        if wanted:
            state.requested_slot_unavailable = True
            return
        candidates = self._filter_by_part_of_day(slots, state.part_of_day)
        if not candidates and state.accept_any_time:
            candidates = slots
        if candidates:
            self._reschedule(state, state.existing_appointment_id, doctor_id, state.date, candidates[0])

    def _find_appointment(self, state: ConversationState, subject_patient_id: str | None) -> str | None:
        """The subject patient's booked appointment (the caller's own, or the
        authorized target's) — `subject_patient_id` is resolved and authorized
        by the caller, and there is deliberately NO fallback to the actor here.

        NOTE: state.date is the TARGET date for a reschedule, not the existing
        appointment's date, so the search is not filtered by it. Preference:
        today's appointment first (cv_0003 'aaj ka'), then the earliest.
        """
        if subject_patient_id is None:
            return None
        candidates = [
            a for a in self.store.all_appointments()
            if a["patient_id"] == subject_patient_id and a["status"] == "booked"
        ]
        if not candidates:
            return None
        todays = [a for a in candidates if a["date"] == state.today]
        if todays:
            return sorted(todays, key=lambda a: a["start"])[0]["id"]
        return sorted(candidates, key=lambda a: (a["date"], a["start"]))[0]["id"]

    def _reschedule(self, state: ConversationState, appointment_id: str, doctor_id: str,
                    date: str, start: str) -> None:
        args = {
            "appointment_id": appointment_id,
            "patient_id": state.actor.patient_id,
            "date": date,
            "start": start,
        }
        result = reschedule_appointment(self.clinic, self.store, args)
        state.record_tool_call("reschedule_appointment", args)
        if result.ok:
            state.action_done = "rescheduled"
            state.appointment_id = appointment_id
            state.final_patient_id = state.actor.patient_id
            state.chosen_slot = start

    # ------------------------------------------------------------------ cancel

    def _try_cancel(self, state: ConversationState) -> None:
        if state.actor.patient_id is None:
            return
        # cv_0009: a third-party mention must NOT become the caller's own
        # appointment: if the caller mentioned another person's name and is
        # not an authorized guardian of that person, escalate immediately.
        subject = state.actor.patient_id
        if state.target_name:
            subject, reason = self._authorized_target(state)
            if reason is not None:
                self._escalate(state, reason, summary=TARGET_ESCALATION_SUMMARIES[reason])
                return

        if state.existing_appointment_id is None:
            state.existing_appointment_id = self._find_appointment(state, subject)
            if state.existing_appointment_id is None:
                return

        args = {"appointment_id": state.existing_appointment_id, "patient_id": state.actor.patient_id}
        result = cancel_appointment(self.clinic, self.store, args)
        state.record_tool_call("cancel_appointment", args)
        if result.ok:
            state.action_done = "cancelled"
            state.appointment_id = state.existing_appointment_id
            state.final_patient_id = state.actor.patient_id

    # ------------------------------------------------------------------ search grounding

    def _search(self, state: ConversationState, doctor_id: str, date: str) -> list[str]:
        key = (doctor_id, (date or ""))
        if key not in state.search_results:
            args = {"doctor_id": doctor_id, "date": date}
            result = search_slots(self.clinic, args)
            state.record_tool_call("search_slots", args)
            state.search_results[key] = result.data["slots"] if result.ok else []
        return state.search_results[key]

    # ------------------------------------------------------------------ outcomes

    def _clear_completed_action(self, state: ConversationState) -> None:
        """Drop the normal-flow outcome so a safety override never reports it.

        The mutation itself already happened and stays recorded in the store and
        in the tool trace; what is withdrawn is the *claim* that this run ended
        in a completed normal action.
        """
        state.chosen_slot = None
        state.appointment_id = None
        state.final_patient_id = None
        state.existing_appointment_id = None

    def _refuse(self, state: ConversationState) -> None:
        state.escalated = False
        state.escalation_reason = None
        state.injection_seen = True
        state.action_done = "refused"
        self._clear_completed_action(state)
        state.reply = "Main sirf appointment booking, rescheduling aur cancellation mein madad kar sakta hoon."
        # cv_0014: no tool calls at all — not even escalate_to_human.

    def _escalate(self, state: ConversationState, reason: str, summary: str) -> None:
        args = {"reason": reason, "summary": summary}
        result = escalate_to_human(self.clinic, self.store, args)
        state.record_tool_call("escalate_to_human", args)
        if result.ok:
            state.escalated = True
            state.escalation_reason = reason
            state.action_done = None
            self._clear_completed_action(state)

    def _finalize(self, state: ConversationState) -> dict[str, Any]:
        reply = state.reply
        terminal_state: str
        escalation_reason = state.escalation_reason

        if state.action_done == "refused":
            terminal_state = "refused"
        elif state.escalated:
            terminal_state = "escalated"
        elif state.action_done == "booked":
            terminal_state = "booked"
        elif state.action_done == "rescheduled":
            terminal_state = "rescheduled"
        elif state.action_done == "cancelled":
            terminal_state = "cancelled"
        else:
            terminal_state, escalation_reason = self._decide_incomplete(state)
            if terminal_state == "escalated" and not state.escalated:
                self._escalate(state, escalation_reason, summary=self._incomplete_summary(state))

        if terminal_state == "booked" and state.chosen_slot:
            reply = f"Ji, aapka appointment {state.date} ko {state.chosen_slot} par book ho gaya hai."
        elif terminal_state == "rescheduled" and state.chosen_slot:
            reply = f"Ji, appointment ab {state.date} ko {state.chosen_slot} par ho gaya hai."
        elif terminal_state == "cancelled":
            reply = "Ji, aapka appointment cancel kar diya gaya hai."
        elif terminal_state == "refused":
            reply = state.reply
        elif terminal_state == "escalated":
            reply = "Main aapko team ke ek member se connect kar raha hoon."
        elif terminal_state == "abandoned":
            reply = "Theek hai, aap jab chahein call kijiye."

        return {
            "conversation_id": state.conversation_id,
            "tool_calls": state.tool_calls,
            # Application-only trace (Phase 7): ordered tool events with the
            # caller-turn index that triggered each. Not part of the
            # schema.md contract; the HTTP layer never emits it.
            "tool_call_events": state.tool_call_events,
            "terminal_state": terminal_state,
            "escalation_reason": escalation_reason if terminal_state == "escalated" else None,
            "patient_id": state.final_patient_id,
            "appointment_id": state.appointment_id,
            "reply": reply,
            "metrics": {"turns": 0, "tokens": 0, "latency_ms": 0},
        }

    def _incomplete_summary(self, state: ConversationState) -> str:
        return (
            f"Unresolved {state.intent or 'request'}; identity unresolved "
            f"(name={state.actor.name!r}, phone={state.actor.phone!r})"
        )

    def _decide_incomplete(self, state: ConversationState) -> tuple[str, str | None]:
        """abandoned vs escalated when no action completed."""
        # cv_0007: intent + unresolved identity matching multiple patients
        if state.intent in ("book", "reschedule", "cancel") and self._identity_ambiguous(state):
            return "escalated", "ambiguous_patient"
        return "abandoned", None

    def _identity_ambiguous(self, state: ConversationState) -> bool:
        if state.actor.patient_id:
            return False
        if state.actor.phone and state.actor.name:
            return False  # concrete identity given but not found -> not ambiguous
        if state.actor.name:
            matches = candidates_by_name(self.clinic, state.actor.name)
            if len(matches) > 1:
                return True
            # cv_0007: surname-only reference matching several real patients
            surname_matches = candidates_by_surname(self.clinic, state.actor.name)
            if len(surname_matches) > 1:
                return True
            # bare first name matching several real patients ('Rajesh') is
            # ambiguous exactly like a surname-only reference
            from app.agent.engine_utils import first_name_matches_count
            return first_name_matches_count(self.clinic, state.actor.name) > 1
        return False


def guardian_check(clinic, guardian_id: str | None, patient_id: str) -> bool:
    if guardian_id is None:
        return False
    guardian = clinic.get_patient(guardian_id)
    return guardian is not None and patient_id in guardian.guardian_of


def normalize_first_name(name: str) -> str:
    tokens = name.replace(".", " ").split()
    return tokens[0].lower() if tokens else ""
