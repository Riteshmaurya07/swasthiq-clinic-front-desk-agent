"""Conversation-script-driven tests using OUR OWN /adversarial scripts.

The supplied evaluation conversations are confidential Swasthiq material and
are not reproduced here. These tests drive the full engine — and the real
HTTP endpoint — with this repository's eight adversarial scripts, asserting
terminal state, escalation reason, must-call/must-not-call tools, and
determinism across repeated runs.
"""

from __future__ import annotations

import json
import pathlib

import pytest
from fastapi.testclient import TestClient

from app.agent.engine import ConversationEngine
from app.clinic import load_clinic
from app.main import app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ADVERSARIAL_DIR = REPO_ROOT / "adversarial"
CLINIC_FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "clinic_fixture.json"


def load_scripts():
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(ADVERSARIAL_DIR.glob("*.json"))]


def matches(script, result) -> bool:
    expected = script["expected"]
    called = {c["name"] for c in result["tool_calls"]}
    return (
        result["terminal_state"] == expected["terminal_state"]
        and result["escalation_reason"] == expected["escalation_reason"]
        and all(t in called for t in expected["must_call"])
        and all(t not in called for t in expected["must_not_call"])
    )


@pytest.fixture(autouse=True)
def _clinic_env(monkeypatch):
    """Point the app at the bundled synthetic clinic fixture."""
    monkeypatch.setenv("CLINIC_JSON_PATH", str(CLINIC_FIXTURE))


@pytest.mark.parametrize("script", load_scripts(), ids=lambda s: s["id"])
def test_engine_passes_own_adversarial_script(script):
    result = ConversationEngine(load_clinic(CLINIC_FIXTURE)).run(script["id"], script["today"], script["turns"])
    assert matches(script, result), (script["id"], result["terminal_state"], result["escalation_reason"], result["tool_calls"])


@pytest.mark.parametrize("script", load_scripts(), ids=lambda s: s["id"])
def test_engine_deterministic_on_own_adversarial_script(script):
    engine_result = ConversationEngine(load_clinic(CLINIC_FIXTURE)).run(script["id"], script["today"], script["turns"])
    fingerprint = (
        engine_result["terminal_state"],
        engine_result["escalation_reason"],
        tuple(sorted({c["name"] for c in engine_result["tool_calls"]})),
    )
    for _ in range(2):
        again = ConversationEngine(load_clinic(CLINIC_FIXTURE)).run(script["id"], script["today"], script["turns"])
        assert (
            again["terminal_state"],
            again["escalation_reason"],
            tuple(sorted({c["name"] for c in again["tool_calls"]})),
        ) == fingerprint


def test_adversarial_directory_has_eight_scripts():
    assert len(load_scripts()) == 8


# ------------------------------------------------------------- HTTP layer

@pytest.fixture(scope="module")
def client(monkeypatch_module):
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(scope="module")
def monkeypatch_module():
    """Module-scoped monkeypatch: point the app at the bundled fixture."""
    import os

    old = os.environ.get("CLINIC_JSON_PATH")
    os.environ["CLINIC_JSON_PATH"] = str(CLINIC_FIXTURE)
    yield
    if old is None:
        os.environ.pop("CLINIC_JSON_PATH", None)
    else:
        os.environ["CLINIC_JSON_PATH"] = old


@pytest.mark.parametrize("script", load_scripts(), ids=lambda s: s["id"])
def test_http_endpoint_matches_own_adversarial_script(client, script):
    response = client.post("/agent/run", json={
        "conversation_id": script["id"],
        "today": script["today"],
        "turns": script["turns"],
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["conversation_id"] == script["id"]
    assert matches(script, body), (script["id"], body["terminal_state"], body["escalation_reason"])


def test_http_response_contract_shape(client):
    script = load_scripts()[0]
    response = client.post("/agent/run", json={
        "conversation_id": script["id"],
        "today": script["today"],
        "turns": script["turns"],
    })
    body = response.json()
    assert set(body) == {
        "conversation_id", "tool_calls", "terminal_state", "escalation_reason",
        "patient_id", "appointment_id", "reply", "metrics",
    }
    for call in body["tool_calls"]:
        assert set(call) == {"name", "arguments"}
    assert set(body["metrics"]) == {"turns", "tokens", "latency_ms"}


def test_http_state_isolation_between_requests(client):
    """The same conversation run twice must book the same slot: request A's
    store cannot leak into request B."""
    script = load_scripts()[0]
    responses = [
        client.post("/agent/run", json={
            "conversation_id": script["id"], "today": script["today"], "turns": script["turns"],
        }).json()
        for _ in range(2)
    ]
    assert responses[0]["terminal_state"] == responses[1]["terminal_state"]
    if responses[0]["appointment_id"]:
        assert responses[0]["appointment_id"] == responses[1]["appointment_id"]
