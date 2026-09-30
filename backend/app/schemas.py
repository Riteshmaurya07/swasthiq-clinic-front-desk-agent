"""Typed request/response contracts for the POST /agent/run endpoint.

Defined now (Phase 1) so later phases can share one vocabulary; nothing here
talks to the network or an LLM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TERMINAL_STATES = frozenset(
    {"booked", "rescheduled", "cancelled", "escalated", "refused", "abandoned"}
)
ESCALATION_REASONS = frozenset(
    {"clinical_urgent", "medical_advice", "not_authorised", "ambiguous_patient", "out_of_scope"}
)


@dataclass(frozen=True)
class AgentRunRequest:
    conversation_id: str
    today: str  # YYYY-MM-DD; the only "now" the conversation knows
    turns: tuple[str, ...]


@dataclass(frozen=True)
class ToolCall:
    name: str
    arguments: dict = field(default_factory=dict)


@dataclass
class AgentRunResponse:
    conversation_id: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    terminal_state: str = "abandoned"
    escalation_reason: str | None = None
    patient_id: str | None = None
    appointment_id: str | None = None
    reply: str = ""
    metrics: dict = field(default_factory=dict)

    def validate(self) -> list[str]:
        """Contract checks mirroring runner.py; returns a list of problems."""
        problems: list[str] = []
        if self.terminal_state not in TERMINAL_STATES:
            problems.append(f"terminal_state {self.terminal_state!r} not in {sorted(TERMINAL_STATES)}")
        if self.terminal_state == "escalated":
            if self.escalation_reason not in ESCALATION_REASONS:
                problems.append(f"escalation_reason {self.escalation_reason!r} required and invalid")
        elif self.escalation_reason is not None:
            problems.append("escalation_reason must be null unless terminal_state is 'escalated'")
        if not isinstance(self.reply, str):
            problems.append("reply must be a string")
        return problems
