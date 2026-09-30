"""Conversation timeline capture.

The engine's contract result carries name/arguments per tool call; the
dashboard additionally needs to know WHEN in the caller-turn sequence each
call happened, plus a full ordered timeline of (caller turn / tool call /
agent reply). This module derives the timeline from existing structures
without altering the evaluator's output contract in any way.

No event timestamps are fabricated; ordering uses sequence numbers only.
"""

from __future__ import annotations

from typing import Any


def build_timeline(
    turns: list[str],
    engine_events: list[dict[str, Any]],
    reply: str = "",
) -> list[dict[str, Any]]:
    """Interleave caller turns and engine events into one ordered timeline.

    Engine events are ``{"turn_index": i, "kind": "tool", "name": ...,
    "arguments": ..., "result": ...}``. Events are emitted grouped by the
    caller turn that triggered them, so sorting by (turn_index, engine_seq)
    reconstructs the exact order.

    The final agent event carries the conversation's actual reply text.
    """
    timeline: list[dict[str, Any]] = []
    for index, turn in enumerate(turns):
        timeline.append({"seq": len(timeline), "kind": "caller", "text": turn})
        for event in engine_events:
            if event["turn_index"] == index:
                timeline.append({
                    "seq": len(timeline),
                    "kind": "tool_call",
                    "name": event["name"],
                    "arguments": event["arguments"],
                    "result": event.get("result"),
                })
    if turns or reply:
        timeline.append({"seq": len(timeline), "kind": "agent", "text": reply})
    return timeline


def build_tool_call_records(
    tool_calls: list[dict[str, Any]],
    engine_events: list[dict[str, Any]],
    conversation_id: str,
) -> list[dict[str, Any]]:
    """Ordered ToolCallRecord inputs, preserving the evaluator's tool order.

    Each record keeps the contract's name/arguments and, where known, the
    turn_index at which the call happened. No results are fabricated: the
    engine contract does not expose per-tool results, so ``result`` stays
    None and the timeline carries status only via position.
    """
    records = []
    for sequence, call in enumerate(tool_calls):
        turn_index = next(
            (e["turn_index"] for e in engine_events
             if e["name"] == call["name"] and e["arguments"] == call["arguments"]),
            None,
        )
        records.append({
            "conversation_id": conversation_id,
            "sequence": sequence,
            "tool_name": call["name"],
            "arguments": call["arguments"],
            "result": None,
            "turn_index": turn_index,
        })
    return records
