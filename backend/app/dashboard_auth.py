"""Dashboard session authentication (H-2 remediation).

Why this module exists
----------------------
The dashboard read/write API (``/api/conversations*``, ``/api/handoffs*``)
returns patient identities, phone numbers, conversation transcripts and the
clinical handoff queue. It previously had **no authentication at all**, so
anyone who could reach the deployed host could read that data and mark
handoffs resolved. That was audit finding H-2.

Design
------
* Credentials come from the environment only:
  ``DASHBOARD_ADMIN_USERNAME`` / ``DASHBOARD_ADMIN_PASSWORD``.
* Sessions are random opaque identifiers. The cookie carries **only** a signed
  session id plus an expiry timestamp — never the username, never the password,
  never the session secret.
* The cookie is signed with HMAC-SHA256 using ``DASHBOARD_SESSION_SECRET`` so a
  forged or edited cookie is rejected before any lookup.
* Server-side state (session id -> expiry) lives in memory. That is what
  makes logout a real invalidation rather than a client-side illusion. It
  deliberately stores **no identity**: the session is a bearer capability, so
  the operator's username never enters the registry and no endpoint can leak it.
* Every comparison is constant-time (``secrets.compare_digest``).

Deliberate non-goals: this is a single-admin session gate for one dashboard, not
an identity provider. See ``DECISIONS.md`` for the rejected alternatives and the
known limitations (in-memory sessions do not survive a process restart or a
multi-worker deploy).
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from dataclasses import dataclass
from hashlib import sha256

from fastapi import HTTPException, Request, Response

# Cookie name is deliberately dashboard-specific so it can never collide with
# anything the evaluator's public /agent/run path relies on.
COOKIE_NAME = "swasthiq_dashboard_session"

# Token format version, bumped if the signing scheme ever changes.
TOKEN_VERSION = "v1"

# A clinic shift is long enough to matter but short enough that an abandoned
# workstation does not keep a session alive all day.
DEFAULT_TTL_SECONDS = 8 * 60 * 60

_UNCONFIGURED_MESSAGE = (
    "Dashboard authentication is not configured. Set DASHBOARD_ADMIN_USERNAME, "
    "DASHBOARD_ADMIN_PASSWORD and DASHBOARD_SESSION_SECRET before starting the server."
)


# ------------------------------------------------------------------ config


def _env(name: str) -> str:
    """Read an environment variable, treating whitespace-only as unset.

    Read per request rather than cached at import time so tests (and a
    reconfigured deployment) can change configuration without a reload.
    """
    value = os.environ.get(name, "")
    return value.strip() if isinstance(value, str) else ""


def admin_username() -> str:
    return _env("DASHBOARD_ADMIN_USERNAME")


def admin_password() -> str:
    return _env("DASHBOARD_ADMIN_PASSWORD")


def session_secret() -> str:
    return _env("DASHBOARD_SESSION_SECRET")


def auth_configured() -> bool:
    """True only when all three settings are present.

    Fails closed: an unconfigured server can never issue a valid session, so a
    forgotten environment variable denies access instead of opening it.
    """
    return bool(admin_username() and admin_password() and session_secret())


def session_ttl_seconds() -> int:
    raw = _env("DASHBOARD_SESSION_TTL_SECONDS")
    if raw.isdigit() and int(raw) > 0:
        return int(raw)
    return DEFAULT_TTL_SECONDS


def cookie_secure() -> bool:
    """Whether to set the ``Secure`` cookie attribute.

    Secure cookies are unusable over plain http, so a bare local ``uvicorn`` run
    needs them off. Everything else — an explicit production setting, or any
    recognised PaaS — defaults to Secure, so forgetting the flag in a real
    deployment fails safe rather than shipping the cookie in the clear.
    """
    explicit = _env("DASHBOARD_COOKIE_SECURE").lower()
    if explicit:
        return explicit in {"1", "true", "yes", "on"}
    env = _env("DASHBOARD_ENV").lower()
    if env:
        return env == "production"
    return any(_env(name) for name in ("RENDER", "VERCEL", "FLY_APP_NAME", "DYNO", "RAILWAY_ENVIRONMENT"))


# ------------------------------------------------------------- credentials


def verify_credentials(username: str, password: str) -> bool:
    """Constant-time credential check that leaks neither value nor which failed.

    Both comparisons always run so the response time does not reveal whether the
    username or the password was the wrong one.
    """
    expected_user = admin_username()
    expected_pass = admin_password()
    if not auth_configured():
        return False
    user_ok = hmac.compare_digest(str(username), expected_user)
    pass_ok = hmac.compare_digest(str(password), expected_pass)
    return user_ok and pass_ok


# ---------------------------------------------------------------- sessions


@dataclass(frozen=True)
class _Session:
    expires_at: float


_lock = threading.Lock()
_sessions: dict[str, _Session] = {}


def _prune_locked(now: float) -> None:
    for sid in [s for s, v in _sessions.items() if v.expires_at <= now]:
        del _sessions[sid]


def create_session() -> str:
    """Issue a new session and return the signed cookie value."""
    if not auth_configured():
        raise RuntimeError(_UNCONFIGURED_MESSAGE)
    ttl = session_ttl_seconds()
    now = time.time()
    session_id = secrets.token_urlsafe(32)
    with _lock:
        _prune_locked(now)
        _sessions[session_id] = _Session(expires_at=now + ttl)
    return _sign(session_id, now + ttl)


def destroy_session(cookie_value: str | None) -> None:
    """Invalidate a session server-side. Logout is idempotent."""
    session_id = _unsign(cookie_value)
    if not session_id:
        return
    with _lock:
        _sessions.pop(session_id, None)


def reset_sessions() -> None:
    """Drop every session. Test-only helper; never called by the app."""
    with _lock:
        _sessions.clear()


def session_is_valid(cookie_value: str | None) -> bool:
    """True when the cookie carries a signature-matching, unexpired, known session.

    Returns a boolean rather than an identity on purpose: nothing outside this
    module needs to know who is signed in, so no caller can accidentally
    serialise the username into a response.
    """
    session_id = _unsign(cookie_value)
    if not session_id:
        return False
    now = time.time()
    with _lock:
        _prune_locked(now)
        return session_id in _sessions


def _sign(session_id: str, expires_at: float) -> str:
    payload = f"{TOKEN_VERSION}.{session_id}.{expires_at:.0f}"
    return f"{payload}.{_signature(payload)}"


def _signature(payload: str) -> str:
    mac = hmac.new(session_secret().encode("utf-8"), payload.encode("utf-8"), sha256)
    return mac.hexdigest()


def _unsign(cookie_value: str | None) -> str | None:
    """Validate the signature and expiry, then return the session id.

    Returns ``None`` for anything malformed, unsigned, tampered with, signed with
    a different secret, or expired.
    """
    if not cookie_value or not auth_configured():
        return None
    parts = cookie_value.split(".")
    if len(parts) != 4:
        return None
    version, session_id, expires_raw, signature = parts
    if version != TOKEN_VERSION or not session_id or not expires_raw.isdigit():
        return None
    payload = f"{version}.{session_id}.{expires_raw}"
    if not hmac.compare_digest(signature, _signature(payload)):
        return None
    if int(expires_raw) <= time.time():
        return None
    return session_id


# ------------------------------------------------------------------ cookie


def set_session_cookie(response: Response, cookie_value: str) -> None:
    """Attach the HttpOnly session cookie."""
    response.set_cookie(
        key=COOKIE_NAME,
        value=cookie_value,
        max_age=session_ttl_seconds(),
        httponly=True,
        secure=cookie_secure(),
        samesite="none" if cookie_secure() else "lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        samesite="none" if cookie_secure() else "lax",
        secure=cookie_secure(),
    )


# -------------------------------------------------------------- dependency


def require_dashboard_session(request: Request) -> None:
    """FastAPI dependency: require a valid dashboard session or raise 401.

    Applied to ``/api/conversations*`` and ``/api/handoffs*`` only. The public
    evaluator contract (``POST /agent/run``) and ``GET /health`` deliberately do
    not depend on this.

    Returns ``None``: the session is a bearer capability, so no protected handler
    receives an identity and none can leak the operator's username.
    """
    if not session_is_valid(request.cookies.get(COOKIE_NAME)):
        raise HTTPException(
            status_code=401,
            detail="Dashboard authentication required. Sign in at /api/auth/login.",
        )