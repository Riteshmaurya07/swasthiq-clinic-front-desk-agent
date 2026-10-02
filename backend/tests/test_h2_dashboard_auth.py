"""H-2 regression tests: dashboard APIs must require an authenticated session.

H-2 was an unauthenticated data exposure: on the previous deployment anyone who
could reach the host could read conversation transcripts, patient identities and
the clinical handoff queue, and could mark handoffs resolved.

What these tests pin down:
  * every dashboard route answers 401 without a session, including the PATCH
  * a wrong password never produces a session
  * a valid login does, and the resulting cookie is an HttpOnly signed session
  * logout genuinely invalidates the session server-side
  * no dashboard payload ever reaches an unauthenticated caller
  * the public evaluator contract (/agent/run, /health) is untouched
  * credentials and secrets never appear in a response body, a Set-Cookie
    header, or the log stream

Credentials used here are hardcoded synthetic values defined in ``conftest.py``.
They are not real credentials and are not used by any deployment.
"""

from __future__ import annotations

import logging
import pathlib
import time

import pytest
from fastapi.testclient import TestClient

from app.dashboard_auth import (
    COOKIE_NAME,
    DEFAULT_TTL_SECONDS,
    cookie_secure,
    session_ttl_seconds,
    session_is_valid,
)
from app.main import app
from conftest import (
    DASHBOARD_TEST_PASSWORD,
    DASHBOARD_TEST_SECRET,
    DASHBOARD_TEST_USERNAME,
    login_to_dashboard,
)

# Every dashboard route that exposes patient data or clinical state.
PROTECTED_GETS = [
    "/api/conversations",
    "/api/conversations/cv_h2_probe",
    "/api/handoffs",
    "/api/handoffs/stats",
]
PROTECTED_PATCH = "/api/handoffs/cv_h2_probe/resolve"

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.fixture()
def client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Unauthenticated client on a throwaway application DB.

    Deliberately does *not* sign in: these tests must prove the unauthenticated
    path, so any accidental login here would invalidate the whole file.
    """
    import app.main as main_module

    monkeypatch.setattr(main_module, "DATABASE_PATH", tmp_path / "app.db")
    monkeypatch.setenv("CLINIC_JSON_PATH", str(REPO_ROOT / "backend/tests/fixtures/clinic_fixture.json"))
    with TestClient(main_module.app) as test_client:
        yield test_client


def adversarial_turns(index: int) -> list[str]:
    """Turn list from this repository's own adversarial script (no starter pack)."""
    import json

    script = REPO_ROOT / "adversarial" / f"case_{index:04d}.json"
    return json.loads(script.read_text(encoding="utf-8"))["turns"]


def seed_data(client: TestClient) -> None:
    """Store one conversation + handoff so 401s cannot be confused with 404s.

    Without real rows, a broken auth check could still look like a 401 for the
    wrong reason; with rows, a 200 would be an unambiguous leak. Uses the repo's
    own clinical_urgent script, which produces a real handoff row.
    """
    response = client.post("/agent/run", json={
        "conversation_id": "cv_h2_probe",
        "today": "2026-10-01",
        "turns": adversarial_turns(1),  # chest pain -> escalated -> handoff created
    })
    assert response.status_code == 200, response.text
    assert response.json()["terminal_state"] == "escalated"


# ------------------------------------------- 1-5: unauthenticated is refused


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_dashboard_get_requires_session(client, path):
    seed_data(client)
    response = client.get(path)
    assert response.status_code == 401, response.text


def test_dashboard_resolve_requires_session(client):
    seed_data(client)
    response = client.patch(PROTECTED_PATCH, json={})
    assert response.status_code == 401, response.text


@pytest.mark.parametrize("path", PROTECTED_GETS + [PROTECTED_PATCH])
def test_unauthenticated_401_body_is_a_clear_auth_error(client, path):
    seed_data(client)
    method = "patch" if path == PROTECTED_PATCH else "get"
    response = getattr(client, method)(path, **({"json": {}} if method == "patch" else {}))
    assert response.status_code == 401
    assert "auth" in response.json()["detail"].lower()


def test_unauthenticated_resolve_does_not_change_handoff_state(client):
    """A refused PATCH must not have resolved anything."""
    seed_data(client)
    login_to_dashboard(client)
    before = client.get("/api/handoffs?status=open").json()
    client.cookies.clear()

    assert client.patch(PROTECTED_PATCH, json={}).status_code == 401

    login_to_dashboard(client)
    after = client.get("/api/handoffs?status=open").json()
    assert {h["conversation_id"] for h in before["handoffs"]} == {h["conversation_id"] for h in after["handoffs"]}


# ----------------------------------------------- 10: no data to anonymous calls


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_no_dashboard_data_leaks_to_unauthenticated_caller(client, path):
    """The 401 body must not carry any patient or clinical data."""
    seed_data(client)
    method = getattr(client, "patch" if path == PROTECTED_PATCH else "get")
    kwargs = {"json": {}} if path == PROTECTED_PATCH else {}
    response = method(path, **kwargs)
    body = response.text
    assert response.status_code == 401
    for leak in ("Neha", "9812200404", "seena mein dard", "transcript", "handoffs", "terminal_state"):
        assert leak not in body, f"{path} leaked {leak!r}"


def test_unauthenticated_handoffs_response_has_no_rows(client):
    seed_data(client)
    response = client.get("/api/handoffs?status=open")
    assert response.status_code == 401
    assert "handoffs" not in response.json()


# ------------------------------------------------------- 6-7: the login flow


def test_invalid_password_is_rejected(client):
    response = client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": "wrong-password",
    })
    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies


def test_unknown_username_is_rejected(client):
    response = client.post("/api/auth/login", json={
        "username": "nobody",
        "password": DASHBOARD_TEST_PASSWORD,
    })
    assert response.status_code == 401
    assert COOKIE_NAME not in response.cookies


def test_wrong_username_and_wrong_password_are_indistinguishable(client):
    """No oracle for which factor was wrong."""
    bad_user = client.post("/api/auth/login", json={"username": "nobody", "password": DASHBOARD_TEST_PASSWORD})
    bad_pass = client.post("/api/auth/login", json={"username": DASHBOARD_TEST_USERNAME, "password": "nope"})
    assert bad_user.status_code == bad_pass.status_code == 401
    assert bad_user.json() == bad_pass.json()


def test_valid_login_creates_a_session(client):
    response = client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    })
    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert COOKIE_NAME in response.cookies


# --------------------------------------------------- 8: authenticated works


@pytest.mark.parametrize("path", PROTECTED_GETS)
def test_authenticated_dashboard_requests_succeed(client, path):
    seed_data(client)
    login_to_dashboard(client)
    response = client.get(path)
    assert response.status_code == 200, response.text


def test_authenticated_resolve_succeeds(client):
    seed_data(client)
    login_to_dashboard(client)
    response = client.patch(PROTECTED_PATCH, json={})
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"


def test_auth_me_reports_only_authentication_state(client):
    """`/api/auth/me` must not name the operator.

    The configured username is a credential component, so the session is an
    anonymous bearer capability and the response carries authentication state
    only.
    """
    login_to_dashboard(client)
    response = client.get("/api/auth/me")
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert DASHBOARD_TEST_USERNAME not in response.text


def test_login_response_does_not_echo_the_username(client):
    response = client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    })
    assert response.status_code == 200
    assert response.json() == {"authenticated": True}
    assert DASHBOARD_TEST_USERNAME not in response.text
    assert DASHBOARD_TEST_PASSWORD not in response.text


def test_auth_me_without_session_is_401(client):
    assert client.get("/api/auth/me").status_code == 401


# ------------------------------------------------- 9: logout really logs out


def test_logout_invalidates_the_session(client):
    login_to_dashboard(client)
    assert client.get("/api/conversations").status_code == 200

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200
    assert logout_response.json()["authenticated"] is False

    # The browser would have dropped the cookie; a stale copy must not work either.
    client.cookies.clear()
    assert client.get("/api/conversations").status_code == 401


def test_replayed_cookie_is_refused_after_logout(client):
    """Server-side invalidation, not just 'the client forgot the cookie'."""
    seed_data(client)
    login_to_dashboard(client)
    stolen = client.cookies.get(COOKIE_NAME)
    assert stolen

    client.post("/api/auth/logout")
    client.cookies.set(COOKIE_NAME, stolen)  # attacker replays the old cookie
    assert client.get("/api/conversations").status_code == 401


def test_logout_without_a_session_is_idempotent(client):
    assert client.post("/api/auth/logout").status_code == 200


# ------------------------------------- 11-12: public contract is unaffected


def test_agent_run_still_works_without_a_session(client):
    response = client.post("/agent/run", json={
        "conversation_id": "cv_public_probe",
        "today": "2026-10-01",
        "turns": adversarial_turns(4),  # guardian booking
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["terminal_state"] == "booked"


def test_health_still_works_without_a_session(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_agent_run_contract_is_unchanged_by_auth(client):
    """Shape and semantics must match schema.md exactly, as before H-2."""
    body = client.post("/agent/run", json={
        "conversation_id": "cv_contract_probe",
        "today": "2026-10-01",
        "turns": ["Mujhe kal Dr. Rao ke saath appointment chahiye."],
    }).json()
    assert set(body) == {
        "conversation_id", "tool_calls", "terminal_state", "escalation_reason",
        "patient_id", "appointment_id", "reply", "metrics",
    }
    assert body["conversation_id"] == "cv_contract_probe"


# -------------------------------------------- security properties of the cookie


def _session_cookie(response) -> str:
    return response.headers["set-cookie"]


def test_cookie_is_httponly(client):
    header = _session_cookie(client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    }))
    assert "httponly" in header.lower()


def test_cookie_is_samesite_lax(client):
    header = _session_cookie(client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    }))
    assert "samesite=lax" in header.lower()


def test_cookie_is_not_secure_in_development(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENV", "development")
    assert cookie_secure() is False


def test_cookie_is_secure_in_production(monkeypatch):
    monkeypatch.setenv("DASHBOARD_ENV", "production")
    assert cookie_secure() is True


def test_cookie_is_secure_on_recognised_paas_even_without_env(monkeypatch):
    """Forgetting DASHBOARD_ENV on a real deployment must still ship Secure."""
    monkeypatch.delenv("DASHBOARD_ENV", raising=False)
    monkeypatch.delenv("DASHBOARD_COOKIE_SECURE", raising=False)
    monkeypatch.setenv("RENDER", "1")
    assert cookie_secure() is True


def test_cookie_has_a_bounded_expiry(client):
    header = _session_cookie(client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    }))
    assert f"max-age={DEFAULT_TTL_SECONDS}" in header.lower()
    assert session_ttl_seconds() == DEFAULT_TTL_SECONDS


def test_cookie_carries_no_username_password_or_secret(client):
    """The cookie must hold only the signed session id and its expiry."""
    response = client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    })
    header = _session_cookie(response)
    assert DASHBOARD_TEST_USERNAME not in header
    assert DASHBOARD_TEST_PASSWORD not in header
    assert DASHBOARD_TEST_SECRET not in header
    value = client.cookies.get(COOKIE_NAME)
    assert value.startswith("v1.")
    assert DASHBOARD_TEST_USERNAME not in value


def test_tampered_cookie_is_rejected(client):
    login_to_dashboard(client)
    good = client.cookies.get(COOKIE_NAME)
    session_id = good.split(".")[1]
    client.cookies.set(COOKIE_NAME, f"v1.{session_id}.9999999999.{good.split('.')[3]}")
    assert client.get("/api/conversations").status_code == 401


def test_cookie_signed_with_another_secret_is_rejected(client, monkeypatch):
    login_to_dashboard(client)
    stolen = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    # Same session id, re-signed by someone who guesses the format but not the secret.
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "a-completely-different-secret")
    assert not session_is_valid(stolen)


def test_unknown_session_id_is_rejected(client):
    login_to_dashboard(client)
    good = client.cookies.get(COOKIE_NAME)
    client.cookies.set(COOKIE_NAME, good)  # signature still valid
    import app.dashboard_auth as auth

    auth.reset_sessions()  # server forgot the session (e.g. after a restart)
    assert not session_is_valid(good)


def test_expired_session_is_rejected(client):
    """A correctly signed token whose expiry has passed must still be refused.

    The signature is valid and the session id is genuinely registered, so this
    isolates the expiry check: without it an eight-hour-old cookie would work
    forever.
    """
    import app.dashboard_auth as auth

    login_to_dashboard(client)
    good = client.cookies.get(COOKIE_NAME)
    _version, session_id, _expires, _signature = good.split(".")
    past = int(time.time()) - 60
    replayed = auth._sign(session_id, past)  # valid signature, stale expiry
    assert auth.session_is_valid(replayed) is False

    client.cookies.set(COOKIE_NAME, replayed)
    assert client.get("/api/conversations").status_code == 401


def test_rotating_the_session_secret_invalidates_issued_sessions(client, monkeypatch):
    """Rotation is the kill switch: every issued cookie dies at once."""
    login_to_dashboard(client)
    live = client.cookies.get(COOKIE_NAME)
    import app.dashboard_auth as auth

    assert auth.session_is_valid(live) is True
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "a-brand-new-rotated-secret")
    assert auth.session_is_valid(live) is False

    client.cookies.set(COOKIE_NAME, live)
    assert client.get("/api/conversations").status_code == 401


# ------------------------------------------- secrets must never be disclosed


def test_secrets_never_appear_in_any_response(client):
    login_to_dashboard(client)
    responses = [
        client.post("/api/auth/login", json={
            "username": DASHBOARD_TEST_USERNAME, "password": DASHBOARD_TEST_PASSWORD,
        }),
        client.get("/api/auth/me"),
        client.get("/api/conversations"),
        client.get("/api/handoffs"),
        client.get("/api/handoffs/stats"),
        client.post("/api/auth/logout"),
    ]
    for response in responses:
        text = response.text
        for secret in (DASHBOARD_TEST_PASSWORD, DASHBOARD_TEST_SECRET):
            assert secret not in text


def test_failed_login_logs_no_credentials(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.post("/api/auth/login", json={
            "username": DASHBOARD_TEST_USERNAME,
            "password": "a-wrong-password-value",
        })
    logged = caplog.text
    assert DASHBOARD_TEST_PASSWORD not in logged
    assert DASHBOARD_TEST_SECRET not in logged
    assert "a-wrong-password-value" not in logged


def test_successful_login_logs_no_credentials(client, caplog):
    with caplog.at_level(logging.DEBUG):
        login_to_dashboard(client)
    logged = caplog.text
    assert DASHBOARD_TEST_PASSWORD not in logged
    assert DASHBOARD_TEST_SECRET not in logged


def test_dashboard_auth_module_hardcodes_no_credentials():
    """No literal secret may live in the auth source."""
    source = REPO_ROOT.joinpath("backend", "app", "dashboard_auth.py").read_text(encoding="utf-8")
    assert DASHBOARD_TEST_PASSWORD not in source
    assert DASHBOARD_TEST_SECRET not in source
    for marker in ("password = \"", "secret = \"", "admin_password=\""):
        assert marker not in source


# ------------------------------------------- fail closed when unconfigured


def test_dashboard_denies_access_when_auth_is_unconfigured(client, monkeypatch):
    """A forgotten environment variable must deny, never open."""
    monkeypatch.setenv("DASHBOARD_ADMIN_USERNAME", "")
    monkeypatch.setenv("DASHBOARD_ADMIN_PASSWORD", "")
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    assert client.get("/api/conversations").status_code == 401
    assert client.get("/api/handoffs").status_code == 401


def test_login_reports_unconfigured_server(client, monkeypatch):
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    response = client.post("/api/auth/login", json={
        "username": DASHBOARD_TEST_USERNAME,
        "password": DASHBOARD_TEST_PASSWORD,
    })
    assert response.status_code == 503
    assert response.json()["error"] == "dashboard_auth_not_configured"
    assert COOKIE_NAME not in response.cookies


def test_existing_session_dies_when_secret_is_removed(client, monkeypatch):
    """Rotating the secret invalidates every cookie issued under the old one."""
    login_to_dashboard(client)
    monkeypatch.setenv("DASHBOARD_SESSION_SECRET", "")
    assert client.get("/api/conversations").status_code == 401


# --------------------------------------------- committed-file hygiene


def test_env_example_contains_placeholders_only():
    text = REPO_ROOT.joinpath(".env.example").read_text(encoding="utf-8")
    assert "DASHBOARD_ADMIN_USERNAME=" in text
    assert "DASHBOARD_ADMIN_PASSWORD=" in text
    assert "DASHBOARD_SESSION_SECRET=" in text
    # Placeholders only: no value on the right-hand side.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("DASHBOARD_ADMIN_USERNAME=", "DASHBOARD_ADMIN_PASSWORD=", "DASHBOARD_SESSION_SECRET=")):
            assert stripped.split("=", 1)[1].strip() == "", f"real value committed: {line}"


def test_env_files_stay_ignored():
    result = subprocess_git("check-ignore", "-q", ".env")
    assert result == 0, ".env must be gitignored"


def test_no_dashboard_credentials_in_tracked_files():
    """The synthetic test values must not have leaked into tracked sources."""
    for relative in (
        "README.md", "DECISIONS.md", ".env.example",
        "backend/app/main.py", "backend/app/dashboard_auth.py",
    ):
        text = REPO_ROOT.joinpath(relative).read_text(encoding="utf-8")
        assert DASHBOARD_TEST_PASSWORD not in text, relative
        assert DASHBOARD_TEST_SECRET not in text, relative


def subprocess_git(*args: str) -> int:
    import subprocess

    return subprocess.run(
        ["git", *args], cwd=REPO_ROOT, capture_output=True, check=False,
    ).returncode