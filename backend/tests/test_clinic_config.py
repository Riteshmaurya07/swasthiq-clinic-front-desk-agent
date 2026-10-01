import os
import pytest
from fastapi.testclient import TestClient

from app.clinic import load_clinic, ClinicDataUnavailable
from app.main import app

def test_missing_clinic_file():
    with pytest.raises(ClinicDataUnavailable, match="Configured clinic file not found"):
        load_clinic("does_not_exist.json")

def test_invalid_clinic_file(tmp_path):
    invalid_file = tmp_path / "invalid.json"
    invalid_file.write_text("{bad_json")
    with pytest.raises(ClinicDataUnavailable, match="Invalid or unreadable JSON"):
        load_clinic(invalid_file)

def test_no_path_configured(monkeypatch):
    monkeypatch.delenv("CLINIC_JSON_PATH", raising=False)
    with pytest.raises(ClinicDataUnavailable, match="No clinic data configured"):
        load_clinic(None)

def test_api_returns_clean_error(monkeypatch):
    monkeypatch.delenv("CLINIC_JSON_PATH", raising=False)
    import app.main as main_module
    monkeypatch.setattr(main_module, "CLINIC_JSON_PATH", None)

    client = TestClient(app)
    response = client.post("/agent/run", json={
        "conversation_id": "c1",
        "today": "2026-10-01",
        "turns": []
    })
    assert response.status_code == 500
    data = response.json()
    assert data["error"] == "clinic_data_unavailable"
    assert "No clinic data configured" in data["message"]
