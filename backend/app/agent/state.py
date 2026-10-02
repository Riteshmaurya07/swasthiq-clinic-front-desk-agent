"""Per-conversation state for the orchestration layer.

The state evolves deterministically from the fixed turn sequence; it never
depends on wall-clock time or sampling. `today` comes from the request.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ActorInfo:
    name: str | None = None
    phone: str | None = None
    patient_id: str | None = None


@dataclass
class ConversationState:
    conversation_id: str
    today: str

    # intent / action under way
    intent: str | None = None  # book | reschedule | cancel

    # people
    actor: ActorInfo = field(default_factory=ActorInfo)
    target_name: str | None = None
    target_patient_id: str | None = None
    target_mentioned: bool = False  # a third-party/dependent was referenced
    target_match_count: int = 0  # records the last target name matched (>1 = ambiguous)

    # request parameters (latest explicit value wins)
    doctor_id: str | None = None
    date: str | None = None
    alternate_dates: list[str] = field(default_factory=list)
    time: str | None = None
    part_of_day: str | None = None  # morning | evening | afternoon
    accept_any_time: bool = False
    existing_appointment_id: str | None = None

    # bookkeeping
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    # ordered tool events for the application timeline (Phase 7). Each entry
    # is {name, arguments, turn_index}; the contract's tool_calls entries
    # above stay exactly {name, arguments}.
    tool_call_events: list[dict[str, Any]] = field(default_factory=list)
    current_turn_index: int = -1  # index of the turn being processed
    search_results: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    requested_slot_unavailable: bool = False
    chosen_slot: str | None = None
    injection_seen: bool = False
    caller_disengaged: bool = False

    # outcomes
    escalated: bool = False
    escalation_reason: str | None = None
    action_done: str | None = None  # booked | rescheduled | cancelled
    appointment_id: str | None = None
    final_patient_id: str | None = None
    reply: str = ""

    def record_tool_call(self, name: str, arguments: dict) -> None:
        self.tool_calls.append({"name": name, "arguments": arguments})
        self.tool_call_events.append({
            "name": name,
            "arguments": arguments,
            "turn_index": self.current_turn_index,
        })

    @property
    def finished(self) -> bool:
        return self.escalated or self.action_done is not None
