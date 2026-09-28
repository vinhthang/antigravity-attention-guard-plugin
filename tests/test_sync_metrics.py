import json
import os
import sys
import sqlite3
import tempfile
import time
from unittest.mock import MagicMock, patch
import pytest

repo_root = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
scripts_dir = os.path.join(repo_root, "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from sync_metrics import (
    format_iso_timestamp,
    fetch_events,
    send_metric_event,
    sync_events,
    DEFAULT_EVENT_TYPES,
)


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "attention_guard.db")
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE events (
                event_id TEXT PRIMARY KEY,
                type TEXT,
                payload TEXT,
                created_at REAL
            )
        """)
        now = 1700000000.0
        events = [
            ("ev-1", "PRIMARY_TOOL_DENIED", json.dumps({"tool": "rm"}), now),
            ("ev-2", "STOP_REQUESTED", json.dumps({"reason": "done"}), now + 1),
            ("ev-3", "TURN_CLOSED", json.dumps({}), now + 2),
            ("ev-4", "OTHER_EVENT", json.dumps({}), now + 3),
        ]
        conn.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", events)
        conn.commit()
        conn.close()
        yield db_path


def test_format_iso_timestamp():
    ts = 1700000000.0
    iso = format_iso_timestamp(ts)
    assert "2023-11-14" in iso
    assert format_iso_timestamp("2026-09-28T12:00:00Z") == "2026-09-28T12:00:00Z"


def test_fetch_events_default_filter(temp_db):
    events = fetch_events(temp_db, sync_all=False)
    types = [e["type"] for e in events]
    assert set(types) == set(DEFAULT_EVENT_TYPES)
    assert "OTHER_EVENT" not in types
    assert len(events) == 3


def test_fetch_events_all_and_limit(temp_db):
    all_events = fetch_events(temp_db, sync_all=True)
    assert len(all_events) == 4

    limited = fetch_events(temp_db, sync_all=True, limit=2)
    assert len(limited) == 2


def test_sync_events_dry_run(temp_db):
    res = sync_events(db_path=temp_db, dry_run=True, sync_all=False)
    assert res["total"] == 3
    assert res["synced"] == 3
    assert res["failed"] == 0
    assert res["batches"] == 1


def test_send_metric_event():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 201
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        ok, msg = send_metric_event(
            server_url="https://metrics.example.com",
            event_type="PRIMARY_TOOL_DENIED",
            payload={"tool": "rm"},
            created_at_iso="2026-09-28T12:00:00Z",
            headers={"Content-Type": "application/json"}
        )
        assert ok is True
        assert "HTTP 201" in msg
        mock_urlopen.assert_called_once()
