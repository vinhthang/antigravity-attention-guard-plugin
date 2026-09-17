import time
#!/usr/bin/env python3
import json
import os
import io
import tempfile
import pytest

import sys
import importlib.util

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from ledger import Ledger
from fsm import Event

spec = importlib.util.spec_from_file_location(
    "attention_check",
    os.path.join(os.path.dirname(__file__), "../scripts/attention-check.py")
)
attention_check_mod = importlib.util.module_from_spec(spec)
sys.modules["attention_check"] = attention_check_mod
spec.loader.exec_module(attention_check_mod)

@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)

def run_hook(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    attention_check_mod.main(argv=["attention-check.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

def create_transcript(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

class TestSubagentSkip:
    def test_subagent_with_token_skipped(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        
        token = "abc-123"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
        payload_data = {"token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
        l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload_data))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do task\\n\\n[ANTIGRAVITY_TOKEN:abc-123]", "step_index": 1}\n'
        )
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": "chk-3",
            "transcriptPath": str(transcript)
        })
        assert result == {"decision": "allow"}

    def test_not_fully_idle_skipped(self):
        result = run_hook({"fullyIdle": False, "modelName": "claude-opus-4.6", "conversationId": "chk-2"})
        assert result == {"decision": "allow"}

class TestStopRejectionLimit:
    def test_direct_primary_agent_closes_without_rejection(self, tmp_path, monkeypatch):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        conv_id = f"chk-direct-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "hello", "step_index": 1},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I did some work directly without subagents."}
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        # Even if in RECOVERY_REQUIRED, active=0 and fail=0 closes turn immediately
        l.insert_event(conv_id, "1", "PreToolUse", "0", "enforce", Event.PRIMARY_TOOL_DENIED.name, json.dumps({"reason": "blocked"}))
    
        result = run_hook(payload)
        assert result == {"decision": "allow"}, "Direct primary agent turn should close immediately without stop rejection"

    def test_allow_if_delegated(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        conv_id = f"chk-delegated-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "hello", "step_index": 1},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "invoke_subagent", "args": {}}],
                "step_index": 1
            }
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        # We need to simulate HANDOFF_PENDING -> EXECUTION_ACTIVE or just WORK_PREPARED
        l.insert_event(conv_id, "1", "PreToolUse", "0", "invoke", Event.WORK_PREPARED.name, json.dumps({"tool": "invoke"}))
    
        result = run_hook(payload)
        assert result == {"decision": "allow"}

    def test_flow_review_question_no_dummy(self, tmp_path):
        conv_id = f"chk-flow-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "How does this code work?", "step_index": 1},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "It works by parsing."}
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        # OPEN state
        result = run_hook(payload)
        assert result == {"decision": "allow"}
    def test_completed_subagent_work_allows_immediate_stop(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        conv_id = f"chk-complete-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "build feature", "step_index": 1},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done."}
        ])

        # Create valid walkthrough.md
        wt = tmp_path / "brain" / conv_id / "walkthrough.md"
        wt.parent.mkdir(parents=True, exist_ok=True)
        wt.write_text("# Walkthrough\nFeature completed.")

        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }

        token = "tok-123"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by) VALUES (?, 1, ?)", (token, "child-1"))
            conn.execute("INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, 'TERMINATED', ?, ?, ?, '1', '1')", (token, time.time(), time.time(), conv_id))

        l.insert_event(conv_id, "1", "PreToolUse", "0", "enforce", Event.PRIMARY_TOOL_DENIED.name, json.dumps({"reason": "blocked"}))

        result = run_hook(payload)
        assert result == {"decision": "allow"}

    def test_completed_subagent_work_blocked_without_walkthrough(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        conv_id = f"chk-no-wt-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "build feature", "step_index": 1},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done."}
        ])

        # Note: walkthrough.md is NOT created here!
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }

        token = "tok-456"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by) VALUES (?, 1, ?)", (token, "child-2"))
            conn.execute("INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, 'TERMINATED', ?, ?, ?, '1', '1')", (token, time.time(), time.time(), conv_id))

        # Put FSM into EXECUTION_ACTIVE
        l.insert_event(conv_id, "1", "PreToolUse", "0", "invoke", Event.WORK_PREPARED.name, json.dumps({"tool": "invoke"}))
        l.insert_event(conv_id, "1", "PostToolUse", "0", "invoke", Event.HANDOFF_ACCEPTED.name, json.dumps({}))

        result = run_hook(payload)
        assert result.get("decision") == "continue"
        assert "Walkthrough Gate" in result.get("reason", "")

