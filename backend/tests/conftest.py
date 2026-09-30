"""Shared fixtures for the public test suite.

The original development suite loaded clinic.json from Swasthiq's confidential
starter pack, which is not reproduced in this public repository. The fixtures
below reconstruct an equivalent synthetic clinic from data defined in this
repository (backend/tests/fixtures/clinic_fixture.json) so every unit test
runs without the confidential materials.
"""

from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from app.clinic import Clinic, load_clinic

TESTS_DIR = pathlib.Path(__file__).resolve().parent
CLINIC_JSON = TESTS_DIR / "fixtures" / "clinic_fixture.json"


@pytest.fixture(autouse=True)
def _clinic_data_env(monkeypatch):
    """Point the app's default clinic data at the bundled fixture for every test."""
    monkeypatch.setenv("CLINIC_JSON_PATH", str(CLINIC_JSON))

# Explicit dates only — mirrors the assignment rule: never the system clock.
TODAY = "2026-10-01"  # Thursday
THURSDAY = TODAY
FRIDAY_HOLIDAY = "2026-10-02"
SATURDAY = "2026-10-03"
SUNDAY = "2026-10-04"
# Doctor leave days (matching the fixture clinic's leave_dates).
SETHI_LEAVE_DAY = "2026-10-05"  # dr_sethi on leave 2026-10-05..07
RAO_LEAVE_DAY = "2026-10-09"


@pytest.fixture(scope="session")
def clinic_source_file() -> pathlib.Path:
    """Path to the repository's own synthetic clinic fixture file."""
    assert CLINIC_JSON.exists(), f"missing test fixture: {CLINIC_JSON}"
    return CLINIC_JSON


@pytest.fixture()
def clinic_copy(clinic_source_file: pathlib.Path, tmp_path: pathlib.Path) -> pathlib.Path:
    """A mutable copy of the fixture clinic in a temp dir."""
    copy_path = tmp_path / "clinic.json"
    shutil.copy(clinic_source_file, copy_path)
    return copy_path


@pytest.fixture()
def clinic(clinic_copy: pathlib.Path) -> Clinic:
    return load_clinic(clinic_copy)


@pytest.fixture()
def raw_clinic_json(clinic_copy: pathlib.Path) -> dict:
    with clinic_copy.open(encoding="utf-8") as handle:
        return json.load(handle)


@pytest.fixture()
def app_db(tmp_path: pathlib.Path) -> pathlib.Path:
    """A throwaway SQLite file for application/display records."""
    return tmp_path / "app.db"
