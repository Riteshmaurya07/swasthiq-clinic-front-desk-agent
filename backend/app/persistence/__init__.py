"""SQLite application persistence (Phase 7).

Display/application state for the React dashboard. Deliberately separate
from the evaluator's request-isolated appointment state: nothing here feeds
back into clinic scheduling, and clinic.json is never written.
"""

from app.persistence.database import DATABASE_PATH, connect
from app.persistence.models import ConversationRecord, HandoffRecord, ToolCallRecord
from app.persistence.repositories import (
    ConversationRepository,
    HandoffRepository,
    ToolCallRepository,
)

__all__ = [
    "DATABASE_PATH",
    "ConversationRecord",
    "ConversationRepository",
    "HandoffRecord",
    "HandoffRepository",
    "ToolCallRecord",
    "ToolCallRepository",
    "connect",
]
