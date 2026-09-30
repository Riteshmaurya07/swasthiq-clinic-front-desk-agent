"""Repositories: the only code that touches the SQLite tables.

Multi-statement writes run in a single transaction so a persistence failure
can never leave half-written records.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import timezone

from app.persistence.models import ConversationRecord, HandoffRecord, ToolCallRecord


def _utc_now() -> str:
    from datetime import datetime

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _caller_context(conversation_id: str, turns: list[str]) -> str:
    """Human-context note for the queue: why the caller needed a human.

    The engine emits the last caller utterance; we mirror it here without
    inventing anything. Fallback: the conversation id.
    """
    if turns:
        return turns[-1].strip() or conversation_id
    return conversation_id


class ConversationRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, record: ConversationRecord) -> None:
        cur = self._conn.execute(
            """
            INSERT INTO conversations
                (conversation_id, created_at, today, turns, transcript,
                 terminal_state, escalation_reason, patient_id, appointment_id,
                 reply, tokens, latency_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (conversation_id) DO UPDATE SET
                created_at      = excluded.created_at,
                today           = excluded.today,
                turns           = excluded.turns,
                transcript      = excluded.transcript,
                terminal_state  = excluded.terminal_state,
                escalation_reason = excluded.escalation_reason,
                patient_id      = excluded.patient_id,
                appointment_id  = excluded.appointment_id,
                reply           = excluded.reply,
                tokens          = excluded.tokens,
                latency_ms      = excluded.latency_ms
            """,
            (
                record.conversation_id,
                _utc_now(),
                record.today,
                record.turns_json,
                record.transcript_json,
                record.terminal_state,
                record.escalation_reason,
                record.patient_id,
                record.appointment_id,
                record.reply,
                record.tokens,
                record.latency_ms,
            ),
        )
        self._conn.commit()
        return None

    def get(self, conversation_id: str) -> ConversationRecord | None:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list(self, limit: int = 200) -> list[ConversationRecord]:
        rows = self._conn.execute(
            "SELECT * FROM conversations ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._row_to_record(r) for r in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ConversationRecord:
        return ConversationRecord(
            conversation_id=row["conversation_id"],
            today=row["today"],
            turns=ConversationRecord.loads_turns(row["turns"]),
            terminal_state=row["terminal_state"],
            reply=row["reply"],
            escalation_reason=row["escalation_reason"],
            patient_id=row["patient_id"],
            appointment_id=row["appointment_id"],
            tokens=row["tokens"],
            latency_ms=row["latency_ms"],
            transcript=ConversationRecord.loads_transcript(row["transcript"]),
            id=row["id"],
            created_at=row["created_at"],
        )


class ToolCallRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def replace_for_conversation(
        self, conversation_id: str, calls: list[ToolCallRecord]
    ) -> None:
        """Replace the ordered tool-call trace for one conversation."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM tool_calls WHERE conversation_id = ?", (conversation_id,)
            )
            for call in calls:
                self._conn.execute(
                    """
                    INSERT INTO tool_calls
                        (conversation_id, sequence, tool_name, arguments, result)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        conversation_id,
                        call.sequence,
                        call.tool_name,
                        call.arguments_json,
                        call.result_json,
                    ),
                )

    def list_for_conversation(self, conversation_id: str) -> list[ToolCallRecord]:
        rows = self._conn.execute(
            "SELECT * FROM tool_calls WHERE conversation_id = ? ORDER BY sequence",
            (conversation_id,),
        ).fetchall()
        return [
            ToolCallRecord(
                conversation_id=r["conversation_id"],
                sequence=r["sequence"],
                tool_name=r["tool_name"],
                arguments=ToolCallRecord.loads_arguments(r["arguments"]),
                result=ToolCallRecord.loads_result(r["result"]),
            )
            for r in rows
        ]


class HandoffRepository:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def create(self, record: HandoffRecord) -> HandoffRecord:
        created_at = record.created_at or _utc_now()
        self._conn.execute(
            """
            INSERT INTO handoffs
                (conversation_id, escalation_reason, caller_context,
                 created_at, status)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT (conversation_id) DO NOTHING
            """,
            (
                record.conversation_id,
                record.escalation_reason,
                record.caller_context,
                created_at,
                record.status,
            ),
        )
        self._conn.commit()
        return self.get(record.conversation_id)  # type: ignore[return-value]

    def get(self, conversation_id: str) -> HandoffRecord | None:
        row = self._conn.execute(
            "SELECT * FROM handoffs WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def list(self, status: str | None = None) -> list[HandoffRecord]:
        if status is not None:
            rows = self._conn.execute(
                "SELECT * FROM handoffs WHERE status = ? ORDER BY created_at DESC, id DESC",
                (status,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM handoffs ORDER BY created_at DESC, id DESC"
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def stats(self) -> dict[str, int]:
        row = self._conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END)     AS open,
                SUM(CASE WHEN status = 'resolved' THEN 1 ELSE 0 END) AS resolved
            FROM handoffs
            """
        ).fetchone()
        total = row["total"] or 0
        open_count = row["open"] or 0
        return {
            "total": total,
            "open": open_count,
            "resolved": row["resolved"] or 0,
        }

    def resolve(self, conversation_id: str) -> HandoffRecord | None:
        """Deterministic open -> resolved. Idempotent; unknown id -> None."""
        record = self.get(conversation_id)
        if record is None:
            return None
        if record.status == "resolved":
            return record  # already resolved: clean no-op, state unchanged
        self._conn.execute(
            """
            UPDATE handoffs
            SET status = 'resolved', resolved_at = ?
            WHERE conversation_id = ? AND status = 'open'
            """,
            (_utc_now(), conversation_id),
        )
        self._conn.commit()
        return self.get(conversation_id)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> HandoffRecord:
        return HandoffRecord(
            conversation_id=row["conversation_id"],
            escalation_reason=row["escalation_reason"],
            caller_context=row["caller_context"],
            status=row["status"],
            id=row["id"],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )
