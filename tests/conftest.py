"""Shared fixtures for ascii_adventure test suite."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
import db as db_module


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    """Isolated SQLite DB in a temp directory. Resets module-level connection."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(db_module, "DB_FILE", db_path)
    existing = db_module._conn
    if existing:
        existing.close()
    monkeypatch.setattr(db_module, "_conn", None)
    db_module.init_db()
    yield db_module
    conn = db_module._conn
    if conn:
        conn.close()
    monkeypatch.setattr(db_module, "_conn", None)


@pytest.fixture()
def sample_abilities():
    return {
        "STR":       {"roll": 10, "dice": [3, 3, 4], "mod":  0},
        "AGI":       {"roll": 15, "dice": [5, 5, 5], "mod":  2},
        "PRE":       {"roll":  8, "dice": [2, 3, 3], "mod": -1},
        "TOU":       {"roll": 12, "dice": [4, 4, 4], "mod":  0},
        "KNOWLEDGE": {"roll": 14, "dice": [4, 5, 5], "mod":  1},
    }
