import json
import os
import io
import time
import pytest
import sqlite3
import importlib.util
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from ledger import Ledger
from fsm import Event, State

spec = importlib.util.spec_from_file_location(
    "attention_check",
    os.path.join(os.path.dirname(__file__), "../scripts/attention-check.py")
)
attention_check_mod = importlib.util.module_from_spec(spec)
sys.modules["attention_check"] = attention_check_mod
spec.loader.exec_module(attention_check_mod)

def _run_hook(mod, payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    mod.main(argv=["test"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

@pytest.fixture
def setup_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)
    return tmp_path

def test_turn_zero_completion(setup_env):
    l = Ledger()
    token = "deadbeef-0000-0000-0000-000000000000"
    conv_id = "child-0"
    
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by) VALUES (?, 1, ?)", (token, conv_id))
        conn.execute("INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, 'ACTIVE', ?, ?, 'parent', '0', '0')", (token, time.time(), time.time()))
    
    l.insert_event("parent", "0", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps({
        "token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": 0
    }))
    
    payload = {
        "conversationId": conv_id,
        "transcriptPath": str(setup_env / "transcript.jsonl"),
        "fullyIdle": True,
        "terminationReason": "model_stop",
        "error": None
    }
    
    with open(setup_env / "transcript.jsonl", "w") as f:
        f.write(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 0, "content": f"[ANTIGRAVITY_TOKEN:{token}]"}) + "\n")
        f.write(json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Acknowledged."}) + "\n")
        
    _run_hook(attention_check_mod, payload)
    
    with l._get_connection() as conn:
        assert conn.execute("SELECT status FROM work_items WHERE work_id=?", (token,)).fetchone()[0] in ('COMPLETED', 'TERMINATED')

def test_timeout_handling(setup_env):
    l = Ledger()
    token = "deadbeef-0000-0000-0000-111111111111"
    conv_id = "child-timeout"
    
    old_time = time.time() - 87000  # Older than 24 hours
    
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by) VALUES (?, 1, ?)", (token, conv_id))
        conn.execute("INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, 'ACTIVE', ?, ?, 'parent', '1', '1')", (token, old_time, old_time))
    
    payload = {
        "conversationId": "parent",
        "transcriptPath": str(setup_env / "transcript_parent.jsonl"),
        "fullyIdle": True
    }
    
    with open(setup_env / "transcript_parent.jsonl", "w") as f:
        f.write(json.dumps({"source": "USER_EXPLICIT", "type": "USER_INPUT", "step_index": 1}) + "\n")
    
    l.insert_event("parent", "1", "PreToolUse", "1", token, "WORK_PREPARED", json.dumps({"token": token, "tool": "invoke", "valid_handoff": True, "parent_conv_id": "parent", "parent_turn_id": 1}))
    l.insert_event("parent", "1", "PostToolUse", "1", "invoke", "HANDOFF_ACCEPTED", json.dumps({"error": None}))
    
    res = _run_hook(attention_check_mod, payload)
    assert res.get("decision") == "continue"  # Assert primary agent Stop returns continue (recovery)
    
    with l._get_connection() as conn:
        assert conn.execute("SELECT status FROM work_items WHERE work_id=?", (token,)).fetchone()[0] == 'TIMED_OUT'
        
    # Assert late child success does NOT mutate status back to TERMINATED
    child_payload = {
        "conversationId": conv_id,
        "transcriptPath": str(setup_env / "transcript_child.jsonl"),
        "fullyIdle": True,
        "terminationReason": "model_stop",
        "error": None
    }
    with open(setup_env / "transcript_child.jsonl", "w") as f:
        f.write(json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "content": f"[ANTIGRAVITY_TOKEN:{token}]"}) + "\n")
        
    child_res = _run_hook(attention_check_mod, child_payload)
    assert child_res.get("decision") == "allow"
    
    with l._get_connection() as conn:
        assert conn.execute("SELECT status FROM work_items WHERE work_id=?", (token,)).fetchone()[0] == 'TIMED_OUT'
        # Assert WORK_TERMINATED_OK was NOT inserted
        cursor = conn.execute("SELECT COUNT(*) FROM events WHERE event_id LIKE ? AND type = 'WORK_TERMINATED_OK'", (f"parent_1_%",))
        assert cursor.fetchone()[0] == 0


def test_handoff_pending_primary_tool_denied():
    from fsm import FSM, State, Event
    f = FSM(initial_state=State.HANDOFF_PENDING)
    action = f.transition(Event.PRIMARY_TOOL_DENIED)
    assert f.state == State.RECOVERY_REQUIRED
    assert action == "Write marker"
