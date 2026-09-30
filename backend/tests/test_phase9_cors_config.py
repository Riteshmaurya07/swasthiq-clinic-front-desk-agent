"""Phase 9 regression: production CORS origin configuration.

BACKEND_CORS_ORIGINS (comma-separated) extends the local dev origins without
ever enabling wildcard CORS.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def _reload_main(monkeypatch, cors_origins=None):
    import app.main as main_module

    if cors_origins is None:
        monkeypatch.delenv("BACKEND_CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("BACKEND_CORS_ORIGINS", cors_origins)
    return importlib.reload(main_module)


def test_env_origins_are_allowed(monkeypatch):
    main_module = _reload_main(monkeypatch, "https://desk.example.com, https://desk2.example.com")
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "https://desk.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") == "https://desk.example.com"


def test_local_dev_origins_always_allowed(monkeypatch):
    main_module = _reload_main(monkeypatch, "https://desk.example.com")
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "http://localhost:5173"},
        )
        assert response.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_unlisted_origin_still_rejected(monkeypatch):
    main_module = _reload_main(monkeypatch, "https://desk.example.com")
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "https://evil.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") is None


def test_wildcard_never_used(monkeypatch):
    main_module = _reload_main(monkeypatch, "https://desk.example.com")
    with TestClient(main_module.app) as client:
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "https://desk.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") != "*"


def test_empty_env_keeps_local_only(monkeypatch):
    main_module = _reload_main(monkeypatch, "")
    with TestClient(main_module.app) as client:
        allowed = main_module.app.user_middleware[0].kwargs["allow_origins"]
        assert allowed == ["http://localhost:5173", "http://127.0.0.1:5173"]
        response = client.get(
            "/api/handoffs/stats",
            headers={"Origin": "https://anything.example.com"},
        )
        assert response.headers.get("access-control-allow-origin") is None
