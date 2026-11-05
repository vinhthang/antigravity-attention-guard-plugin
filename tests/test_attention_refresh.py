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


def test_req_031_active_context_chars_and_refresh_calculation(tmp_path):
    """REQ-031: Calculate tokens from active_context_chars (excluding thinking and pre-compaction)."""
    import ledger
    import common
    l = ledger.Ledger()

    t_file = tmp_path / "transcript_with_thinking.jsonl"
    step2_content = "Execute task"
    step3_content = "Finished task execution successfully"
    tool_calls = [{"name": "read_file", "args": {"Path": "/workspace/a.txt"}}]
    tool_calls_str = json.dumps(tool_calls)

    lines = [
        json.dumps({"source": "USER", "type": "USER_INPUT", "content": "Ancient history before compaction" * 100}),
        json.dumps({"source": "MODEL", "type": "COMPACTION", "content": "Context compacted"}),
        json.dumps({"source": "USER", "type": "USER_INPUT", "content": step2_content}),
        json.dumps({
            "source": "MODEL",
            "type": "PLANNER_RESPONSE",
            "content": step3_content,
            "thinking": "MASSIVE THINKING TRACE " * 10000,
            "tool_calls": tool_calls
        }),
    ]
    t_file.write_text("\n".join(lines) + "\n")

    parsed = common.parse_transcript(str(t_file))
    assert parsed.get("has_valid_json_steps") is True
    expected_chars = len(step2_content) + len(step3_content) + len(tool_calls_str)
    assert parsed.get("active_context_chars") == expected_chars

    # Test refresh token volume calculation using active_context_chars
    # If using os.path.getsize // 4, tokens would be > 50,000 and trigger refresh!
    # With active_context_chars // 4 (< 100 tokens), it must NOT trigger refresh on invocation 3
    payload = {
        "transcriptPath": str(t_file),
        "sessionId": "active_ctx_sess",
        "invocationNum": 3
    }
    res = run_hook(payload)
    assert res == {}, "Active context tokens are small (< 20K), so volume refresh should not fire"

    # Verify ledger session_stats was synchronized with active_context_chars
    total_toks, _ = l.get_session_token_stats("active_ctx_sess")
    assert total_toks == expected_chars // 4


def test_build_refresh_reminder_positional_args(tmp_path):
    """Harden build_refresh_reminder positional args and None branches against mutations."""
    import ledger
    l = ledger.Ledger()

    class MockLedger:
        def audit_conversation_budget(self, c_id):
            if c_id == "c_override":
                return {"unique_workers": 88, "prepared_workers": 0}
            return {"unique_workers": 99, "prepared_workers": 0}
        def get_session_token_stats(self, c_id):
            return 4000, 0

    mock_l = MockLedger()

    # len(args) == 1
    rem1 = refresh_mod.build_refresh_reminder("c1", 50000)
    assert "~50,000 tokens" in rem1

    # len(args) == 2 (tests len(args) >= 2 -> args[1] is mock_l)
    rem2 = refresh_mod.build_refresh_reminder("c1", 60000, mock_l)
    assert "~60,000 tokens" in rem2
    assert "Workers: 99" in rem2

    # len(args) == 3 (tests len(args) >= 3 -> args[2] is 'c_override')
    rem3 = refresh_mod.build_refresh_reminder("c1", 70000, mock_l, "c_override")
    assert "~70,000 tokens" in rem3
    assert "Workers: 88" in rem3

    # len(args) == 4 (tests len(args) >= 4 -> args[3] is art_dir)
    art_dir = str(tmp_path / "artifacts_pos")
    rem4 = refresh_mod.build_refresh_reminder("c1", 80000, l, "c_override", art_dir)
    assert "~80,000 tokens" in rem4
    assert os.path.exists(os.path.join(art_dir, "session_checkpoint.md"))

    # ledger=None instantiation and total_tokens=None fallback
    rem_none_both = refresh_mod.build_refresh_reminder("c_none", total_tokens=None, ledger=None)
    assert "Context Telemetry:" in rem_none_both

    # total_tokens=None fetched from ledger
    l.record_tool_chars("c_tokens_none", 16000) # 4000 tokens
    rem_none_tokens = refresh_mod.build_refresh_reminder("c_tokens_none", ledger=l, total_tokens=None)
    assert "~4,000 tokens" in rem_none_tokens

    # token_budget == 0 boundary
    rem_zero_budget = refresh_mod.build_refresh_reminder("c_zero", total_tokens=5000, token_budget=0)
    assert "0.0% of 0k budget" in rem_zero_budget

    # conv_id == 'unknown' does not infer artifact_dir
    rem_unknown = refresh_mod.build_refresh_reminder("unknown", total_tokens=85000, artifact_dir=None)
    assert "Pre-compaction state checkpoint written" not in rem_unknown

    # Checkpoint threshold exact boundary
    chk_dir = str(tmp_path / "chk_boundary")
    rem_chk_exact = refresh_mod.build_refresh_reminder("c_chk", total_tokens=80000, checkpoint_threshold=80000, artifact_dir=chk_dir)
    assert "Pre-compaction state checkpoint written" in rem_chk_exact

    rem_chk_below = refresh_mod.build_refresh_reminder("c_chk", total_tokens=79999, checkpoint_threshold=80000, artifact_dir=chk_dir)
    assert "Pre-compaction state checkpoint written" not in rem_chk_below


def test_emit_reminder_default_text():
    out = io.StringIO()
    refresh_mod._emit_reminder(out, reminder_text=None)
    data = json.loads(out.getvalue().strip())
    assert refresh_mod.PRIMARY_RULES_REMINDER in data["injectSteps"][0]["ephemeralMessage"]


def test_zero_interval_resets_to_default(monkeypatch):
    import ledger
    l = ledger.Ledger()
    l.record_tool_chars("zero_int_sess", 100000)
    monkeypatch.setenv("AGY_ATTENTION_GUARD_REFRESH_INTERVAL", "0")
    # Interval 0 should reset to 25 and not divide by zero
    assert run_hook({"sessionId": "zero_int_sess", "invocationNum": 24}) == {}
    res = run_hook({"sessionId": "zero_int_sess", "invocationNum": 25})
    assert "injectSteps" in res


def test_invocation_zero_boundary_with_tokens():
    import ledger
    l = ledger.Ledger()
    l.record_tool_chars("inv_zero_sess", 100000) # 25000 tokens
    # invocationNum 0 should never trigger modulo reminder
    res = run_hook({"sessionId": "inv_zero_sess", "invocationNum": 0})
    assert res == {}


def test_token_threshold_20000_exact_boundary():
    import ledger
    l = ledger.Ledger()
    # Exactly 20,000 tokens (80,000 chars) -> not suppressed on invocation 25
    l.record_tool_chars("exact_20k_sess", 80000)
    res = run_hook({"sessionId": "exact_20k_sess", "invocationNum": 25})
    assert "injectSteps" in res

    # 19,999 tokens (79,996 chars) -> suppressed on invocation 25
    l.record_tool_chars("below_20k_sess", 79996)
    res_below = run_hook({"sessionId": "below_20k_sess", "invocationNum": 25})
    assert res_below == {}



