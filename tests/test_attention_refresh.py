#!/usr/bin/env python3
import sys
import os
import io
import json
import pytest
import importlib

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "attention_refresh",
    os.path.join(os.path.dirname(__file__), "../scripts/attention-refresh.py")
)
refresh_mod = importlib.util.module_from_spec(spec)
sys.modules["attention_refresh"] = refresh_mod
spec.loader.exec_module(refresh_mod)

@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)
    import common
    importlib.reload(common)

def run_hook(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    refresh_mod.main(stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

def test_kill_switch_suppresses_refresh(monkeypatch):
    monkeypatch.setenv("AGY_ATTENTION_GUARD_KILL_SWITCH", "1")
    res = run_hook({"invocationNum": 25})
    assert res == {}

def test_observation_mode_suppresses_refresh(monkeypatch):
    monkeypatch.setenv("AGY_ATTENTION_GUARD_OBSERVATION_MODE", "1")
    res = run_hook({"invocationNum": 25})
    assert res == {}

def test_fast_path_non_modulo():
    for num in [1, 2, 24, 26, 49, 51]:
        res = run_hook({"invocationNum": num})
        assert res == {}

def test_modulo_zero_and_negative_boundary():
    assert run_hook({"invocationNum": 0}) == {}
    assert run_hook({"invocationNum": -1}) == {}

def test_periodic_refresh_fires_on_cadence():
    for num in [25, 50, 75]:
        res = run_hook({"invocationNum": num})
        assert "injectSteps" in res
        assert len(res["injectSteps"]) == 1
        assert "ephemeralMessage" in res["injectSteps"][0]
        assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]

def test_custom_interval(monkeypatch):
    monkeypatch.setenv("AGY_ATTENTION_GUARD_REFRESH_INTERVAL", "10")
    assert run_hook({"invocationNum": 9}) == {}
    res = run_hook({"invocationNum": 10})
    assert "injectSteps" in res

def test_subagent_skipped(tmp_path):
    import ledger
    l = ledger.Ledger()
    token = "a1b2-c3d4-1234"
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
    payload = {"token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
    l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Task [ANTIGRAVITY_TOKEN:{token}]"}}\n')

    data = {
        "transcriptPath": str(transcript),
        "conversationId": "child-conv",
        "invocationNum": 25
    }
    res = run_hook(data)
    assert res == {}

def test_manifest_integrity():
    manifest_path = os.path.join(os.path.dirname(__file__), "../hooks.json")
    with open(manifest_path, "r") as f:
        data = json.load(f)
    assert "attention-guard-refresh" in data
    assert "PreInvocation" in data["attention-guard-refresh"]
    cmd = data["attention-guard-refresh"]["PreInvocation"][0]["command"]
    assert "attention-refresh.py" in cmd
