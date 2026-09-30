"""Phase 7 tests — SQLite application persistence + read APIs.

Boundary under test: persistence is display-only. It must (a) record every
completed /agent/run, (b) create handoffs only for escalations, (c) never
mutate the clinic data file, and (d) never affect the evaluator's
request-isolated appointment state.

Uses this repository's own /adversarial scripts (the supplied evaluation
conversations are confidential and not shipped).
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from app.persistence import (
    ConversationRepository,
    HandoffRepository,
    ToolCallRepository,
    connect,
)

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADVERSARIAL_DIR = REPO_ROOT / "adversarial"
CLINIC_FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "clinic_fixture.json"

ESCALATED_IDS = {"adv_0001", "adv_0002", "adv_0003"}
BOOKED_ID = "adv_0004"


def load_scripts():
    import json

    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ADVERSARIAL_DIR.glob("*.json"))]


def load_script(conversation_id: str) -> dict:
    return next(s for s in load_scripts() if s["id"] == conversation_id)


@pytest.fixture()
def client(app_db: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient wired to a throwaway application DB + bundled clinic fixture."""
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATABASE_PATH", app_db)
    monkeypatch.setenv("CLINIC_JSON_PATH", str(CLINIC_FIXTURE))
    with TestClient(main_module.app) as test_client:
        yield test_client


def run_conv(client: TestClient, conversation_id: str) -> dict:
    script = load_script(conversation_id)
    response = client.post("/agent/run", json={
        "conversation_id": conversation_id,
        "today": script["today"],
        "turns": script["turns"],
    })
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------- conversations stored

def test_run_creates_conversation_record(client, app_db):
    run_conv(client, BOOKED_ID)
    record = ConversationRepository(connect(app_db)).get(BOOKED_ID)
    assert record is not None
    assert record.terminal_state == "booked"
    assert record.appointment_id is not None
    assert record.reply  # non-empty
    assert record.latency_ms >= 0


def test_conversation_stores_turns_transcript_and_metrics(client, app_db):
    script = load_script("adv_0003")
    run_conv(client, "adv_0003")
    record = ConversationRepository(connect(app_db)).get("adv_0003")
    assert record.turns == script["turns"]
    # transcript: one caller event per turn, plus final agent reply
    kinds = [e["kind"] for e in record.transcript]
    assert kinds.count("caller") == len(script["turns"])
    assert kinds[-1] == "agent"
    # the agent event carries the actual reply text, never a placeholder
    assert record.transcript[-1]["text"] == record.reply
    assert record.transcript[-1]["text"]  # non-empty
    seqs = [e["seq"] for e in record.transcript]
    assert seqs == list(range(len(seqs)))  # ordered by sequence


# ------------------------------------------------------- ordered tool traces

def test_tool_calls_persisted_in_contract_order(client, app_db):
    body = run_conv(client, BOOKED_ID)
    contract_order = [c["name"] for c in body["tool_calls"]]
    calls = ToolCallRepository(connect(app_db)).list_for_conversation(BOOKED_ID)
    assert [c.sequence for c in calls] == list(range(len(calls)))
    assert [c.tool_name for c in calls] == contract_order
    assert calls[-1].tool_name == "book_appointment"  # booking is last
    assert "lookup_patient" in [c.tool_name for c in calls[:2]]  # identity early
    # arguments echo the contract exactly
    booking = calls[-1]
    assert booking.arguments == body["tool_calls"][-1]["arguments"]


def test_tool_call_events_carry_turn_index(client, app_db):
    run_conv(client, BOOKED_ID)
    record = ConversationRepository(connect(app_db)).get(BOOKED_ID)
    # timeline interleaves: no tool event may precede the caller turn
    caller_seqs = {e["seq"] for e in record.transcript if e["kind"] == "caller"}
    tool_events = [e for e in record.transcript if e["kind"] == "tool_call"]
    assert tool_events, "expected at least one tool event"
    for event in tool_events:
        assert event["seq"] > min(caller_seqs)


# ------------------------------------------------------- handoffs on escalation

def test_escalation_creates_open_handoff(client, app_db):
    run_conv(client, "adv_0003")  # ambiguous -> escalated
    handoff = HandoffRepository(connect(app_db)).get("adv_0003")
    assert handoff is not None
    assert handoff.status == "open"
    assert handoff.escalation_reason == "ambiguous_patient"
    assert handoff.caller_context  # last caller turn, non-empty
    assert handoff.resolved_at is None


def test_non_escalated_run_creates_no_handoff(client, app_db):
    run_conv(client, BOOKED_ID)              # booked
    run_conv(client, "adv_0006")             # refused
    assert HandoffRepository(connect(app_db)).list() == []


# ------------------------------------------------------- handoff read APIs

def test_handoff_list_returns_open_records(client):
    run_conv(client, "adv_0003")  # escalated
    run_conv(client, "adv_0002")  # escalated
    run_conv(client, BOOKED_ID)   # booked: no handoff
    body = client.get("/api/handoffs?status=open").json()
    ids = {h["conversation_id"] for h in body["handoffs"]}
    assert ids == {"adv_0003", "adv_0002"}
    assert all(h["status"] == "open" for h in body["handoffs"])


def test_handoff_stats_correct(client):
    run_conv(client, "adv_0003")
    run_conv(client, "adv_0002")
    run_conv(client, BOOKED_ID)
    stats = client.get("/api/handoffs/stats").json()
    assert stats == {"total": 2, "open": 2, "resolved": 0}


def test_handoff_list_rejects_bad_status(client):
    assert client.get("/api/handoffs?status=bogus").status_code == 422


# ------------------------------------------------------- handoff resolution

def test_resolve_changes_state_open_to_resolved(client, app_db):
    run_conv(client, "adv_0003")
    response = client.patch("/api/handoffs/adv_0003/resolve", json={})
    assert response.status_code == 200
    body = response.json()
    assert body["conversation_id"] == "adv_0003"
    assert body["status"] == "resolved"
    assert body["resolved_at"] is not None
    record = HandoffRepository(connect(app_db)).get("adv_0003")
    assert record.status == "resolved"
    assert record.resolved_at is not None


def test_resolve_idempotent_on_already_resolved(client, app_db):
    run_conv(client, "adv_0002")
    first = client.patch("/api/handoffs/adv_0002/resolve", json={})
    assert first.status_code == 200
    resolved_at_first = first.json()["resolved_at"]
    second = client.patch("/api/handoffs/adv_0002/resolve", json={})
    assert second.status_code == 200
    assert second.json()["status"] == "resolved"
    # state must not be corrupted: resolved_at stays the original
    record = HandoffRepository(connect(app_db)).get("adv_0002")
    assert record.resolved_at == resolved_at_first


def test_resolve_unknown_handoff_is_clean_404(client):
    response = client.patch("/api/handoffs/adv_does_not_exist/resolve", json={})
    assert response.status_code == 404


def test_resolving_does_not_delete_conversation_history(client):
    run_conv(client, "adv_0003")
    client.patch("/api/handoffs/adv_0003/resolve", json={})
    detail = client.get("/api/conversations/adv_0003").json()
    assert detail["terminal_state"] == "escalated"
    assert detail["tool_calls"]
    assert detail["transcript"]


# ------------------------------------------------------- conversation detail API

def test_conversation_detail_returns_transcript_tools_outcome(client):
    body = run_conv(client, BOOKED_ID)
    detail = client.get(f"/api/conversations/{BOOKED_ID}").json()
    assert detail["conversation_id"] == BOOKED_ID
    assert detail["terminal_state"] == body["terminal_state"] == "booked"
    assert detail["appointment_id"] == body["appointment_id"]
    assert detail["reply"] == body["reply"]
    assert [c["name"] for c in detail["tool_calls"]] == [
        c["name"] for c in body["tool_calls"]
    ]
    kinds = [e["kind"] for e in detail["transcript"]]
    assert "caller" in kinds and "tool_call" in kinds and "agent" in kinds


def test_conversation_detail_unknown_is_404(client):
    assert client.get("/api/conversations/nope").status_code == 404


def test_conversations_list_shape(client):
    run_conv(client, BOOKED_ID)
    run_conv(client, "adv_0003")
    body = client.get("/api/conversations").json()
    ids = {c["conversation_id"] for c in body["conversations"]}
    assert {BOOKED_ID, "adv_0003"} <= ids
    sample = next(c for c in body["conversations"] if c["conversation_id"] == BOOKED_ID)
    assert sample["terminal_state"] == "booked"
    assert sample["turns"] > 0


# ------------------------------------------------------- boundary: clinic file untouched

def test_persistence_does_not_mutate_clinic_fixture(client):
    before = CLINIC_FIXTURE.read_bytes()
    run_conv(client, BOOKED_ID)    # booking (mutation tools run)
    run_conv(client, "adv_0003")   # escalation -> handoff row
    assert CLINIC_FIXTURE.read_bytes() == before


# ------------------------------------------------------- boundary: evaluator isolation

def test_persistence_side_channel_does_not_leak_appointment_state(client):
    """The SQLite records must not influence subsequent /agent/run results."""
    first = run_conv(client, BOOKED_ID)
    assert first["terminal_state"] == "booked"
    # re-run the same conversation: request-isolated state books identically
    second = run_conv(client, BOOKED_ID)
    assert second["terminal_state"] == "booked"
    assert second["appointment_id"] == first["appointment_id"]


def test_persistence_failure_does_not_break_agent_run(client, app_db, monkeypatch):
    """If the DB write explodes, the evaluator response is still perfect."""
    import app.main as main_module

    def broken_connect(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(main_module, "connect", broken_connect)
    body = run_conv(client, BOOKED_ID)
    assert body["terminal_state"] == "booked"
    assert body["appointment_id"] is not None
    assert main_module.PERSISTENCE_FAILURES >= 1


def test_agent_run_response_contract_unchanged(client):
    body = run_conv(client, BOOKED_ID)
    assert set(body) == {
        "conversation_id", "tool_calls", "terminal_state", "escalation_reason",
        "patient_id", "appointment_id", "reply", "metrics",
    }
    for call in body["tool_calls"]:
        assert set(call) == {"name", "arguments"}


def test_engine_result_not_exposed_via_http(client):
    """tool_call_events stay internal: absent from the HTTP payload."""
    body = run_conv(client, BOOKED_ID)
    assert "tool_call_events" not in body


# ------------------------------------------------------- schema sanity

def test_schema_tables_exist(app_db: pathlib.Path):
    conn = connect(app_db)
    try:
        names = {
            row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    finally:
        conn.close()
    assert {"conversations", "tool_calls", "handoffs"} <= names
