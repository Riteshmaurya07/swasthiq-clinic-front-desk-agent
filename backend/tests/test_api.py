"""API integration tests — exercised over real HTTP (httpx ASGI).

Sources: this repository's own /adversarial scripts (the supplied evaluation
conversations are confidential and not shipped). Isolation is proven through
the endpoint itself: request A's booking cannot influence request B, with no
manual resets anywhere in the test.
"""

from __future__ import annotations

import pathlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADVERSARIAL_DIR = REPO_ROOT / "adversarial"


def load_scripts():
    import json

    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ADVERSARIAL_DIR.glob("*.json"))]


def script_by_id(scripts, script_id):
    return next(s for s in scripts if s["id"] == script_id)


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


def run_conversation(client, script) -> dict:
    response = client.post("/agent/run", json={
        "conversation_id": script["id"],
        "today": script["today"],
        "turns": script["turns"],
    })
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------ scenario coverage

def test_api_escalation_clinical_urgent(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0001")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "escalated"
    assert body["escalation_reason"] == "clinical_urgent"
    assert all(c["name"] != "book_appointment" for c in body["tool_calls"])
    assert "escalate_to_human" in [c["name"] for c in body["tool_calls"]]


def test_api_unauthorized_action(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0002")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "escalated"
    assert body["escalation_reason"] == "not_authorised"
    assert all(c["name"] != "cancel_appointment" for c in body["tool_calls"])


def test_api_ambiguous_patient(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0003")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "escalated"
    assert body["escalation_reason"] == "ambiguous_patient"
    assert body["patient_id"] is None


def test_api_guardian_booking(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0004")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "booked"
    assert body["appointment_id"] is not None
    booking = next(c for c in body["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["patient_id"] == "pt_0007"


def test_api_prompt_injection_refused(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0006")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "refused"
    assert body["escalation_reason"] is None
    # the injection turn is terminal: no mutation tools may run
    assert all(
        c["name"] not in ("cancel_appointment", "book_appointment", "reschedule_appointment")
        for c in body["tool_calls"]
    )


def test_api_accepted_alternative_slot(client):
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0005")
    body = run_conversation(client, script)
    assert body["terminal_state"] == "booked"
    booking = next(c for c in body["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["start"] == "11:00"


def test_api_unavailable_slot_closed_day(client):
    """2026-10-02 is a holiday: nothing bookable, abandoned."""
    response = client.post("/agent/run", json={
        "conversation_id": "t_holiday",
        "today": "2026-10-01",
        "turns": [
            "Dr. Rao ke saath 2 tareekh ka appointment chahiye.",
            "Neha Bhatt, 9812200404.",
        ],
    })
    body = response.json()
    assert body["terminal_state"] == "abandoned"
    assert body["appointment_id"] is None


# ------------------------------------------------------ malformed requests

@pytest.mark.parametrize(
    "payload",
    [
        {},  # empty object
        {"today": "2026-10-01", "turns": []},  # missing conversation_id
        {"conversation_id": 7, "today": "2026-10-01", "turns": []},  # wrong type
        {"conversation_id": "cv_x", "turns": []},  # missing today
        {"conversation_id": "cv_x", "today": "01-10-2026", "turns": []},  # bad format
        {"conversation_id": "cv_x", "today": "2026-13-40", "turns": []},  # impossible date
        {"conversation_id": "cv_x", "today": "2026-10-01"},  # missing turns
        {"conversation_id": "cv_x", "today": "2026-10-01", "turns": "hello"},  # not a list
        {"conversation_id": "cv_x", "today": "2026-10-01", "turns": [1, 2]},  # non-strings
        {"conversation_id": "cv_x", "today": "2026-10-01", "turns": [None]},  # null turn
    ],
)
def test_api_malformed_requests_4xx(client, payload):
    response = client.post("/agent/run", json=payload)
    assert 400 <= response.status_code < 500, (payload, response.status_code)
    assert "terminal_state" not in response.json()


def test_api_malformed_json_body(client):
    response = client.post(
        "/agent/run",
        content="{not json",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= response.status_code < 500


def test_api_empty_body(client):
    response = client.post(
        "/agent/run",
        content="",
        headers={"Content-Type": "application/json"},
    )
    assert 400 <= response.status_code < 500


# ------------------------------------------------ 13-14: contract + echo

def test_api_response_contract_shape(client):
    scripts = load_scripts()
    body = run_conversation(client, scripts[0])
    assert set(body) == {
        "conversation_id", "tool_calls", "terminal_state", "escalation_reason",
        "patient_id", "appointment_id", "reply", "metrics",
    }
    for call in body["tool_calls"]:
        assert set(call) == {"name", "arguments"}
        assert isinstance(call["arguments"], dict)
    assert set(body["metrics"]) == {"turns", "tokens", "latency_ms"}


def test_api_conversation_id_echo(client):
    scripts = load_scripts()
    body = run_conversation(client, scripts[0])
    assert body["conversation_id"] == scripts[0]["id"]


# ------------------------------------------------------ 15: state isolation

def test_api_state_isolation_across_requests(client):
    """Request A books a slot; a repeat of the same request must see the
    original state (no leakage between requests)."""
    scripts = load_scripts()
    script = script_by_id(scripts, "adv_0005")
    body_a = run_conversation(client, script)
    assert body_a["terminal_state"] == "booked"
    appointment_id_a = body_a["appointment_id"]

    body_b = run_conversation(client, script)  # same scenario, fresh store
    assert body_b["terminal_state"] == "booked"
    assert body_b["appointment_id"] == appointment_id_a  # identical outcome


def test_api_isolation_escalation_then_booking(client):
    """An escalation in request A cannot affect request B's booking."""
    scripts = load_scripts()
    run_conversation(client, script_by_id(scripts, "adv_0001"))  # escalated
    body_b = run_conversation(client, script_by_id(scripts, "adv_0007"))
    assert body_b["terminal_state"] == "booked"


# --------------------------------------------- 16: repeated identical request

def test_api_repeated_identical_requests_deterministic(client):
    """Same request 3x -> same terminal_state, reason, tool-name set."""
    for script in load_scripts():
        fingerprints = set()
        for _ in range(3):
            body = run_conversation(client, script)
            names = tuple(sorted({c["name"] for c in body["tool_calls"]}))
            fingerprints.add((body["terminal_state"], body["escalation_reason"], names))
        assert len(fingerprints) == 1, f"{script['id']}: {fingerprints}"


# ------------------------------------------------- 17: no-system-clock

def test_api_today_authoritative_not_system_clock(client):
    """'parso' resolves from the today field even though the real date differs."""
    response = client.post("/agent/run", json={
        "conversation_id": "t_parso",
        "today": "2026-10-01",
        "turns": [
            "Dr. Rao ke saath parso ka appointment chahiye.",
            "Neha Bhatt, 9812200404.",
            "Subah 11 baje theek hai.",
        ],
    })
    body = response.json()
    booking = next(c for c in body["tool_calls"] if c["name"] == "book_appointment")
    assert booking["arguments"]["date"] == "2026-10-03"


def test_api_no_datetime_now_in_main():
    source = pathlib.Path(__file__).resolve().parents[1].joinpath("app", "main.py").read_text(encoding="utf-8")
    assert "datetime.now()" not in source
    assert "datetime.today()" not in source
    assert "date.today()" not in source


# ------------------------------------------------- metrics behavior

def test_api_metrics_turns_and_tokens(client):
    scripts = load_scripts()
    script = scripts[0]
    body = run_conversation(client, script)
    assert body["metrics"]["turns"] == len(script["turns"])
    assert body["metrics"]["tokens"] == 0  # no LLM: report actual usage only
    assert isinstance(body["metrics"]["latency_ms"], int)
    assert body["metrics"]["latency_ms"] >= 0


# ------------------------------------------------- full conversation sweep

def test_api_all_own_adversarial_conversations_match_expected(client):
    scripts = load_scripts()
    passed = 0
    for script in scripts:
        body = run_conversation(client, script)
        expected = script["expected"]
        called = {c["name"] for c in body["tool_calls"]}
        ok = (
            body["terminal_state"] == expected["terminal_state"]
            and body["escalation_reason"] == expected["escalation_reason"]
            and all(t in called for t in expected["must_call"])
            and all(t not in called for t in expected["must_not_call"])
        )
        assert ok, (script["id"], body)
        passed += 1
    assert passed == 8
