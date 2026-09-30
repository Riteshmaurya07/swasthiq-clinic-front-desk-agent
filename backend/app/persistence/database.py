"""SQLite connection/schema bootstrap.

The database stores ONLY application/display records (conversations, tool
traces, handoffs). Appointment availability is never derived from it — the
evaluator's per-request `AppointmentStore` remains the sole source of truth.

Event ordering uses explicit sequence numbers, never wall-clock timestamps.
`created_at`/`resolved_at` are real UTC times for dashboard display only.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Default location: backend/data/app.db (created lazily on first connect).
DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id   TEXT NOT NULL UNIQUE,
    created_at        TEXT NOT NULL,
    today             TEXT NOT NULL,
    turns             TEXT NOT NULL,             -- JSON array of caller turns
    transcript        TEXT NOT NULL,             -- JSON ordered timeline (caller turn / reply events)
    terminal_state    TEXT NOT NULL,
    escalation_reason TEXT,
    patient_id        TEXT,
    appointment_id    TEXT,
    reply             TEXT NOT NULL,
    tokens            INTEGER NOT NULL DEFAULT 0,
    latency_ms        INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tool_calls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    sequence        INTEGER NOT NULL,
    tool_name       TEXT NOT NULL,
    arguments       TEXT NOT NULL,
    result          TEXT,
    UNIQUE (conversation_id, sequence),
    FOREIGN KEY (conversation_id) REFERENCES conversations (conversation_id)
);

CREATE TABLE IF NOT EXISTS handoffs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id    TEXT NOT NULL UNIQUE,
    escalation_reason  TEXT NOT NULL,
    caller_context     TEXT NOT NULL,
    created_at         TEXT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('open', 'resolved')),
    resolved_at        TEXT
);

CREATE INDEX IF NOT EXISTS idx_tool_calls_conversation
    ON tool_calls (conversation_id, sequence);

CREATE INDEX IF NOT EXISTS idx_handoffs_status
    ON handoffs (status, created_at);
"""


def connect(path: Path | str | None = None) -> sqlite3.Connection:
    """Open a connection and ensure the schema exists."""
    db_path = Path(path) if path is not None else DATABASE_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
