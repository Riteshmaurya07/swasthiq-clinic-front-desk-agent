"""Phase 7: SQLite application persistence + frontend read APIs.

Design boundary (assignment requirement): the evaluator's appointment state
stays request-isolated and driven only by clinic.json + AppointmentStore.
This module adds a *display* store — conversations, ordered tool traces, and
handoffs — persisted to SQLite (explicitly permitted by the assignment).

Failure policy: persistence problems are logged and reported via
``/health`` counters but NEVER alter the /agent/run response contract,
status code, or appointment mutation state.
"""

from __future__ import annotations

import logging
import os
import pathlib
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any

# Support `uvicorn backend.app.main:app` from the repo root: the modules in
# this project import each other as `app.*`, which requires backend/ on the
# path. Adding it here is a deployment convenience, not business logic.
_BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app.agent.engine import ConversationEngine
from app.clinic import load_clinic, ClinicDataUnavailable
from app.dashboard_auth import (
    COOKIE_NAME,
    auth_configured,
    clear_session_cookie,
    create_session,
    destroy_session,
    require_dashboard_session,
    set_session_cookie,
    verify_credentials,
)
from app.errors import ToolResult
from app.persistence import (
    ConversationRecord,
    ConversationRepository,
    HandoffRecord,
    HandoffRepository,
    ToolCallRecord,
    ToolCallRepository,
    connect,
)
from app.persistence.timeline import build_timeline, build_tool_call_records
from app.schemas import ESCALATION_REASONS, TERMINAL_STATES
from app.store import AppointmentStore

logger = logging.getLogger("app.persistence")
logger.setLevel(logging.WARNING)
if not logger.handlers:
    logger.addHandler(logging.StreamHandler())

app = FastAPI(title="Swasthiq Clinic Front Desk Agent", version="1.0.0")

# CORS: local Vite dev origins are always allowed. For production deployments,
# set BACKEND_CORS_ORIGINS (comma-separated, e.g. the deployed frontend origin).
# Never "*": the dashboard relies on origin-scoped responses. Read endpoints
# only need GET/PATCH; nothing here weakens the /agent/run evaluator contract.
#
# Credentials are enabled because the dashboard now authenticates with an
# HttpOnly session cookie, which the browser will not attach to a cross-origin
# request unless the server opts in. That is safe only while the origin list
# stays explicit — a wildcard plus credentials would be rejected by the browser
# anyway, and would defeat the point.
_local_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]
_extra_origins = [
    origin.strip()
    for origin in os.environ.get("BACKEND_CORS_ORIGINS", "").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_local_origins + _extra_origins,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type"],
    allow_credentials=True,
)

CLINIC_JSON_PATH = None  # default: the supplied starter-pack file

# Application DB (display records only — never a source of appointment truth).
DATABASE_PATH = pathlib.Path(__file__).resolve().parents[1] / "data" / "app.db"

@app.exception_handler(ClinicDataUnavailable)
def clinic_data_unavailable_handler(request, exc: ClinicDataUnavailable) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={
            "error": "clinic_data_unavailable",
            "message": str(exc),
            "resolution": "Set CLINIC_JSON_PATH to a valid clinic.json file."
        }
    )


# ------------------------------------------------------------------ persistence


def _get_conn() -> sqlite3.Connection:
    """Open (and schema-initialize) the application database."""
    return connect(DATABASE_PATH)


def _persist_run(
    request_payload: dict[str, Any],
    engine_result: dict[str, Any],
    latency_ms: int,
) -> None:
    """Write display records for a completed run. Never raises.

    Records: conversation + ordered tool calls + (escalated only) a handoff.
    A failure here is logged and surfaced via /health; it cannot corrupt the
    evaluator's in-memory appointment state or change the HTTP response.
    """
    try:
        conn = _get_conn()
        try:
            conversation_id = request_payload["conversation_id"]
            turns = engine_result.get("_request_turns", request_payload.get("turns", []))
            events = engine_result.get("tool_call_events", [])

            ConversationRepository(conn).save(ConversationRecord(
                conversation_id=conversation_id,
                today=request_payload["today"],
                turns=list(turns),
                transcript=build_timeline(turns, events, engine_result["reply"]),
                terminal_state=engine_result["terminal_state"],
                escalation_reason=engine_result["escalation_reason"],
                patient_id=engine_result["patient_id"],
                appointment_id=engine_result["appointment_id"],
                reply=engine_result["reply"],
                tokens=0,
                latency_ms=latency_ms,
            ))

            ToolCallRepository(conn).replace_for_conversation(
                conversation_id,
                [
                    ToolCallRecord(
                        conversation_id=conversation_id,
                        sequence=rec["sequence"],
                        tool_name=rec["tool_name"],
                        arguments=rec["arguments"],
                        result=rec["result"],
                    )
                    for rec in build_tool_call_records(
                        engine_result["tool_calls"], events, conversation_id
                    )
                ],
            )

            if engine_result["terminal_state"] == "escalated":
                HandoffRepository(conn).create(HandoffRecord(
                    conversation_id=conversation_id,
                    escalation_reason=engine_result["escalation_reason"] or "unknown",
                    caller_context=turns[-1] if turns else conversation_id,
                    status="open",
                ))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — persistence must never break the run
        logger.exception("application persistence failed; run result unaffected")
        global PERSISTENCE_FAILURES
        PERSISTENCE_FAILURES += 1


PERSISTENCE_FAILURES = 0


# ------------------------------------------------------------------ request


class AgentRunHttpRequest(BaseModel):
    conversation_id: str
    today: str
    turns: list[str]

    @field_validator("conversation_id")
    @classmethod
    def _conversation_id_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("conversation_id must be a non-empty string")
        return value

    @field_validator("today")
    @classmethod
    def _today_is_valid_date(cls, value: str) -> str:
        from app.clinic import parse_date

        parse_date(value)  # strict YYYY-MM-DD; raises ValueError -> 422
        return value

    @field_validator("turns")
    @classmethod
    def _turns_are_strings(cls, value: list[str]) -> list[str]:
        if any(not isinstance(t, str) for t in value):
            raise ValueError("every turn must be a string")
        return value


# ------------------------------------------------------------------ response validation


def _validate_response(payload: dict[str, Any], request: AgentRunHttpRequest) -> list[str]:
    """Contract checks mirroring schema.md (and runner.check_contract).

    Returns a list of problems; an empty list means the payload is valid.
    """
    problems: list[str] = []
    if payload.get("conversation_id") != request.conversation_id:
        problems.append("conversation_id does not echo the request")
    if payload.get("terminal_state") not in TERMINAL_STATES:
        problems.append(f"terminal_state {payload.get('terminal_state')!r} not allowed")
    reason = payload.get("escalation_reason")
    if payload["terminal_state"] == "escalated":
        if reason not in ESCALATION_REASONS:
            problems.append(f"escalation_reason {reason!r} invalid for escalated")
    elif reason is not None:
        problems.append("escalation_reason must be null unless escalated")
    tool_calls = payload.get("tool_calls")
    if not isinstance(tool_calls, list):
        problems.append("tool_calls must be a list")
    else:
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict) or not isinstance(call.get("name"), str) or not isinstance(call.get("arguments"), dict):
                problems.append(f"tool_calls[{index}] needs string 'name' and object 'arguments'")
    if not isinstance(payload.get("reply"), str):
        problems.append("reply must be a string")
    metrics = payload.get("metrics")
    if not isinstance(metrics, dict):
        problems.append("metrics must be an object")
    else:
        for key in ("turns", "tokens", "latency_ms"):
            if key not in metrics:
                problems.append(f"metrics missing {key!r}")
    return problems


def _tool_result_to_dict(result: ToolResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "data": result.data,
        "error": None if result.error is None else {
            "code": result.error.code,
            "message": result.error.message,
            "details": result.error.details,
        },
    }


# ------------------------------------------------------------------ endpoint


@app.post("/agent/run")
def agent_run(request: AgentRunHttpRequest) -> JSONResponse:
    started = time.monotonic()

    # 1. request-local mutable state: fresh clinic + fresh store per request.
    clinic = load_clinic(CLINIC_JSON_PATH)
    store = AppointmentStore(clinic)

    # 2. engine (model=None -> deterministic; no LLM is required or used)
    engine = ConversationEngine(clinic, store=store, model=None)
    result = engine.run(request.conversation_id, request.today, request.turns)
    latency_ms = int((time.monotonic() - started) * 1000)

    # 3. assemble the schema.md payload
    payload: dict[str, Any] = {
        "conversation_id": request.conversation_id,
        "tool_calls": result["tool_calls"],
        "terminal_state": result["terminal_state"],
        "escalation_reason": result["escalation_reason"],
        "patient_id": result["patient_id"],
        "appointment_id": result["appointment_id"],
        "reply": result["reply"],
        "metrics": {
            "turns": len(request.turns),
            "tokens": 0,  # no LLM in this deployment: report actual usage (zero)
            "latency_ms": latency_ms,
        },
    }

    # 4. fail closed on internal corruption rather than emitting bad output
    problems = _validate_response(payload, request)
    if problems:
        return JSONResponse(
            status_code=500,
            content={"error": "internal_response_validation_failed", "problems": problems},
        )

    # 5. application/display persistence (Phase 7) — after the validated
    #    payload is final; failures are logged, never surfaced to the caller.
    #    The validated payload dict is passed directly (it carries turns).
    _persist_run(
        {
            "conversation_id": payload["conversation_id"],
            "today": request.today,
            "turns": request.turns,
        },
        result,
        latency_ms,
    )

    return JSONResponse(status_code=200, content=payload)


@app.get("/health")
def health() -> dict[str, Any]:
    """Dev/deploy convenience only; not part of the evaluation contract."""
    return {"status": "ok", "persistence_failures": PERSISTENCE_FAILURES}


# ------------------------------------------------------ dashboard auth (H-2)
#
# The dashboard read/write APIs below expose patient identities, transcripts and
# the clinical handoff queue, so they require a session issued here. The public
# evaluator endpoints (POST /agent/run, GET /health) are deliberately excluded.


class DashboardLoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
def dashboard_login(payload: DashboardLoginRequest) -> Response:
    """Exchange environment-configured credentials for a session cookie.

    The response body echoes nothing back at all — not the username, not the
    password, not the session id, not the secret — and nothing about either
    credential is written to the log, so an operator learns that a login failed
    but never who tried or with what.
    """
    if not auth_configured():
        return JSONResponse(
            status_code=503,
            content={
                "error": "dashboard_auth_not_configured",
                "message": (
                    "Dashboard authentication is not configured on this server."
                ),
            },
        )
    if not verify_credentials(payload.username, payload.password):
        logger.warning("dashboard login rejected: invalid credentials")
        return JSONResponse(
            status_code=401,
            content={"error": "invalid_credentials", "message": "Invalid username or password."},
        )
    cookie_value = create_session()
    response = JSONResponse(
        status_code=200,
        content={"authenticated": True},
    )
    set_session_cookie(response, cookie_value)
    return response


@app.post("/api/auth/logout")
def dashboard_logout(request: Request) -> Response:
    """Invalidate the session server-side and expire the cookie.

    Idempotent: an absent or already-invalid session still returns 200 with the
    cookie cleared, so the client never has to distinguish the two cases.
    """
    destroy_session(request.cookies.get(COOKIE_NAME))
    response = JSONResponse(status_code=200, content={"authenticated": False})
    clear_session_cookie(response)
    return response


@app.get("/api/auth/me")
def dashboard_me(_session: None = Depends(require_dashboard_session)) -> dict[str, Any]:
    """Report that a valid session exists. 401 when there is not one.

    Reports authentication state only. It deliberately does not name the
    signed-in operator: the session is a bearer capability, so the configured
    username is never echoed into a response body or into the browser.
    """
    return {"authenticated": True}


# ------------------------------------------------------------------ read APIs (Phase 7)

def _conversation_detail(record: ConversationRecord, conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "conversation_id": record.conversation_id,
        "created_at": record.created_at,
        "today": record.today,
        "turns": record.turns,
        "transcript": record.transcript,
        "terminal_state": record.terminal_state,
        "escalation_reason": record.escalation_reason,
        "patient_id": record.patient_id,
        "appointment_id": record.appointment_id,
        "reply": record.reply,
        "metrics": {"turns": len(record.turns), "tokens": record.tokens, "latency_ms": record.latency_ms},
        "tool_calls": [
            {
                "sequence": call.sequence,
                "name": call.tool_name,
                "arguments": call.arguments,
                "result": call.result,
            }
            for call in ToolCallRepository(conn).list_for_conversation(record.conversation_id)
        ],
    }


@app.get("/api/conversations")
def list_conversations(
    _session: None = Depends(require_dashboard_session),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        records = ConversationRepository(conn).list()
    finally:
        conn.close()
    return {
        "conversations": [
            {
                "conversation_id": r.conversation_id,
                "created_at": r.created_at,
                "today": r.today,
                "terminal_state": r.terminal_state,
                "escalation_reason": r.escalation_reason,
                "patient_id": r.patient_id,
                "appointment_id": r.appointment_id,
                "turns": len(r.turns),
            }
            for r in records
        ]
    }


@app.get("/api/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    _session: None = Depends(require_dashboard_session),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        record = ConversationRepository(conn).get(conversation_id)
        if record is None:
            raise HTTPException(status_code=404, detail="conversation not found")
        return _conversation_detail(record, conn)
    finally:
        conn.close()


@app.get("/api/handoffs")
def list_handoffs(
    status: str | None = None,
    _session: None = Depends(require_dashboard_session),
) -> dict[str, Any]:
    if status is not None and status not in ("open", "resolved"):
        raise HTTPException(status_code=422, detail="status must be 'open' or 'resolved'")
    conn = _get_conn()
    try:
        records = HandoffRepository(conn).list(status)
    finally:
        conn.close()
    return {
        "handoffs": [
            {
                "conversation_id": r.conversation_id,
                "escalation_reason": r.escalation_reason,
                "caller_context": r.caller_context,
                "status": r.status,
                "created_at": r.created_at,
                "resolved_at": r.resolved_at,
            }
            for r in records
        ]
    }


@app.get("/api/handoffs/stats")
def handoff_stats(
    _session: None = Depends(require_dashboard_session),
) -> dict[str, int]:
    conn = _get_conn()
    try:
        return HandoffRepository(conn).stats()
    finally:
        conn.close()


class HandoffResolveRequest(BaseModel):
    resolver_note: str | None = None  # optional display note; no clinical fields


@app.patch("/api/handoffs/{conversation_id}/resolve")
def resolve_handoff(
    conversation_id: str,
    request: HandoffResolveRequest | None = None,
    _session: None = Depends(require_dashboard_session),
) -> dict[str, Any]:
    conn = _get_conn()
    try:
        resolved = HandoffRepository(conn).resolve(conversation_id)
    finally:
        conn.close()
    if resolved is None:
        raise HTTPException(status_code=404, detail="handoff not found")
    return {
        "conversation_id": resolved.conversation_id,
        "status": resolved.status,
        "resolved_at": resolved.resolved_at,
    }
