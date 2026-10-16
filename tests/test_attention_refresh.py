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
    import ledger
    l = ledger.Ledger()
    l.record_tool_chars("default", 100000)
    for num in [25, 50, 75]:
        res = run_hook({"invocationNum": num})
        assert "injectSteps" in res
        assert len(res["injectSteps"]) == 1
        assert "ephemeralMessage" in res["injectSteps"][0]
        assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]

def test_custom_interval(monkeypatch):
    import ledger
    l = ledger.Ledger()
    l.record_tool_chars("default", 100000)
    monkeypatch.setenv("AGY_ATTENTION_GUARD_REFRESH_INTERVAL", "10")
    assert run_hook({"invocationNum": 9}) == {}
    res = run_hook({"invocationNum": 10})
    assert "injectSteps" in res

def test_volume_trigger_fires_regardless_of_invocation():
    import ledger
    l = ledger.Ledger()
    # 40000 tokens * 4 = 160000 chars
    l.record_tool_chars("vol_sess", 160000)
    # invocationNum is 3 (not a multiple of 25)
    res = run_hook({"sessionId": "vol_sess", "invocationNum": 3})
    assert "injectSteps" in res
    assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]
    total, since_refresh = l.get_session_token_stats("vol_sess")
    assert since_refresh == 0
    assert total == 40000
    assert l.get_last_refreshed_tokens("vol_sess") == 40000

def test_suppression_low_token_volume():
    import ledger
    l = ledger.Ledger()
    # Less than 20000 tokens (5000 tokens = 20000 chars)
    l.record_tool_chars("low_sess", 20000)
    res = run_hook({"sessionId": "low_sess", "invocationNum": 25})
    assert res == {}

def test_standard_trigger_with_sufficient_tokens():
    import ledger
    l = ledger.Ledger()
    # >= 20000 tokens (25000 tokens = 100000 chars)
    l.record_tool_chars("std_sess", 100000)
    res = run_hook({"sessionId": "std_sess", "invocationNum": 25})
    assert "injectSteps" in res
    assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]
    total, since_refresh = l.get_session_token_stats("std_sess")
    assert since_refresh == 0
    assert total == 25000
    assert l.get_last_refreshed_tokens("std_sess") == 25000

def test_record_tool_result_accumulates_chars():
    import importlib.util
    spec_rec = importlib.util.spec_from_file_location(
        "record_tool_result",
        os.path.join(os.path.dirname(__file__), "../scripts/record-tool-result.py")
    )
    rec_mod = importlib.util.module_from_spec(spec_rec)
    spec_rec.loader.exec_module(rec_mod)

    import ledger
    l = ledger.Ledger()
    payload = {
        "sessionId": "tool_sess",
        "tool_input_str": "a" * 400,
        "tool_output_str": "b" * 400
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    rec_mod.main(stdin=stdin, stdout=stdout)
    assert json.loads(stdout.getvalue().strip()) == {}

    total, since_refresh = l.get_session_token_stats("tool_sess")
    assert total == 800 // 4
    assert since_refresh == 800 // 4

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

def test_ledger_session_refresh_state():
    import ledger
    l = ledger.Ledger()
    # Non-existent session returns 0
    assert l.get_last_refreshed_tokens("non_existent") == 0

    # Record refresh
    l.record_refresh("test_sess", 42000)
    assert l.get_last_refreshed_tokens("test_sess") == 42000

    # Upsert updates tokens
    l.record_refresh("test_sess", 85000)
    assert l.get_last_refreshed_tokens("test_sess") == 85000

def test_transcript_volume_trigger_and_no_retrigger(tmp_path):
    import ledger
    l = ledger.Ledger()
    t_file = tmp_path / "transcript.jsonl"
    # 160000 bytes // 4 = 40000 tokens (>= 40K tokens)
    t_file.write_text("x" * 160000)
    payload = {
        "transcriptPath": str(t_file),
        "sessionId": "trans_vol_sess",
        "invocationNum": 3
    }
    res = run_hook(payload)
    assert "injectSteps" in res
    assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]
    assert l.get_last_refreshed_tokens("trans_vol_sess") == 40000

    # Subsequent call with same transcript size does not re-trigger (tokens_since_refresh == 0)
    res2 = run_hook(payload)
    assert res2 == {}
    assert l.get_last_refreshed_tokens("trans_vol_sess") == 40000

def test_transcript_turn_modulo_suppression_low_volume(tmp_path):
    t_file = tmp_path / "transcript.jsonl"
    # 40000 bytes // 4 = 10000 tokens (< 20K tokens / 80KB)
    t_file.write_text("x" * 40000)
    payload = {
        "transcriptPath": str(t_file),
        "sessionId": "trans_low_sess",
        "invocationNum": 25
    }
    res = run_hook(payload)
    assert res == {}

def test_transcript_turn_modulo_emits_reminder_high_volume(tmp_path):
    import ledger
    l = ledger.Ledger()
    t_file = tmp_path / "transcript.jsonl"
    # 90000 bytes // 4 = 22500 tokens (>= 20K tokens / 80KB, but < 40K tokens)
    t_file.write_text("x" * 90000)
    payload = {
        "transcriptPath": str(t_file),
        "sessionId": "trans_mod_sess",
        "invocationNum": 25
    }
    res = run_hook(payload)
    assert "injectSteps" in res
    assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]
    assert l.get_last_refreshed_tokens("trans_mod_sess") == 22500

def test_fallback_to_ledger_session_stats_when_transcript_missing():
    import ledger
    l = ledger.Ledger()
    # 160000 chars = 40000 tokens
    l.record_tool_chars("fb_sess", 160000)
    # Missing transcriptPath key
    res = run_hook({"sessionId": "fb_sess", "invocationNum": 2})
    assert "injectSteps" in res
    assert "Attention Guard Reminder" in res["injectSteps"][0]["ephemeralMessage"]
    assert l.get_last_refreshed_tokens("fb_sess") == 40000

    # Empty transcriptPath string
    l.record_refresh("fb_sess_empty", 0)
    l.record_tool_chars("fb_sess_empty", 160000)
    res2 = run_hook({"sessionId": "fb_sess_empty", "transcriptPath": "", "invocationNum": 2})
    assert "injectSteps" in res2
    assert l.get_last_refreshed_tokens("fb_sess_empty") == 40000

    # Non-existent transcriptPath file
    l.record_tool_chars("fb_sess_nonexist", 100000)
    res3 = run_hook({"sessionId": "fb_sess_nonexist", "transcriptPath": "/no/such/file.jsonl", "invocationNum": 25})
    assert "injectSteps" in res3
    assert l.get_last_refreshed_tokens("fb_sess_nonexist") == 25000

