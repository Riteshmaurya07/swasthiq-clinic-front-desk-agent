"""Typed records for the application persistence layer."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ConversationRecord:
    conversation_id: str
    today: str
    turns: list[str]
    terminal_state: str
    reply: str
    escalation_reason: str | None = None
    patient_id: str | None = None
    appointment_id: str | None = None
    tokens: int = 0
    latency_ms: int = 0
    # ordered transcript events: {"kind": "caller"|"agent", "text": ...}
    transcript: list[dict[str, Any]] = field(default_factory=list)
    id: int | None = None
    created_at: str | None = None

    @property
    def turns_json(self) -> str:
        return json.dumps(self.turns, ensure_ascii=False)

    @property
    def transcript_json(self) -> str:
        return json.dumps(self.transcript, ensure_ascii=False)

    @staticmethod
    def loads_turns(raw: str) -> list[str]:
        return json.loads(raw)

    @staticmethod
    def loads_transcript(raw: str) -> list[dict[str, Any]]:
        return json.loads(raw)


@dataclass
class ToolCallRecord:
    conversation_id: str
    sequence: int
    tool_name: str
    arguments: dict[str, Any]
    result: dict[str, Any] | None = None

    @property
    def arguments_json(self) -> str:
        return json.dumps(self.arguments, ensure_ascii=False, sort_keys=True)

    @property
    def result_json(self) -> str | None:
        return None if self.result is None else json.dumps(self.result, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def loads_arguments(raw: str) -> dict[str, Any]:
        return json.loads(raw)

    @staticmethod
    def loads_result(raw: str | None) -> dict[str, Any] | None:
        return None if raw is None else json.loads(raw)


@dataclass
class HandoffRecord:
    conversation_id: str
    escalation_reason: str
    caller_context: str
    status: str  # open | resolved
    id: int | None = None
    created_at: str | None = None
    resolved_at: str | None = None
