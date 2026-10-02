"""Phase 8 regression: CORS allows the React dev server's read calls.

The evaluator contract is untouched: /agent/run is POST and unaffected by
the browser preflight rules added for the dashboard.

The dashboard read APIs require a session since the H-2 remediation, so these
tests sign in first. CORS itself is middleware-level and applies regardless of
authentication, which is exactly what is under test here.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from conftest import login_to_dashboard


def test_cors_allows_vite_dev_origin_for_reads():
    with TestClient(app) as client:
        login_to_dashboard(client)
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.status_code == 200
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_cors_rejects_unknown_origin():
    with TestClient(app) as client:
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") is None


def test_cors_allows_patch_for_resolve():
    with TestClient(app) as client:
        response = client.options(
            "/api/handoffs/some_conv/resolve",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "PATCH",
            },
        )
        assert response.status_code == 200
        assert "PATCH" in response.headers.get("access-control-allow-methods", "")


def test_cors_allows_post_for_login():
    """H-2: sign-in and sign-out are POST, so the preflight must allow it."""
    with TestClient(app) as client:
        response = client.options(
            "/api/auth/login",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200
        assert "POST" in response.headers.get("access-control-allow-methods", "")


def test_cors_never_pairs_wildcard_origin_with_credentials():
    """A credentialed wildcard would let any site replay the session cookie.

    This is the single most dangerous CORS misconfiguration, so it is asserted
    directly rather than inferred from the allowlist.
    """
    with TestClient(app) as client:
        login_to_dashboard(client)
        for origin in ("http://localhost:5173", "https://evil.example.com", "*"):
            response = client.get(
                "/api/handoffs/stats",
                headers={"Origin": origin},
            )
            allowed = response.headers.get("access-control-allow-origin")
            assert allowed != "*", f"wildcard reflected for {origin}"


def test_cors_sets_allow_credentials_for_an_allowed_origin():
    """Without this header the browser drops the cookie and the dashboard breaks."""
    with TestClient(app) as client:
        login_to_dashboard(client)
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.headers.get("access-control-allow-credentials") == "true"
