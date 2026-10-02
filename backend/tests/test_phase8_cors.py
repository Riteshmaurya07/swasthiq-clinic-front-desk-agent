"""Phase 8 regression: CORS allows the React dev server's read calls.

The evaluator contract is untouched: /agent/run is POST and unaffected by
the browser preflight rules added for the dashboard.

The dashboard read APIs are tested here. CORS itself is middleware-level and applies regardless of
authentication.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_cors_allows_vite_dev_origin_for_reads():
    with TestClient(app) as client:
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
