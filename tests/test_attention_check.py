#!/usr/bin/env python3
import json
import os
import io
import tempfile
import pytest

import sys
import importlib.util

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
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        token_file = os.path.join(cache_dir, "agy_issued_token_abc-123")
        with open(token_file, "w") as f:
            json.dump({"issuer": "parent", "recipient": None}, f)

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do task\\n\\n[ANTIGRAVITY_TOKEN:abc-123]"}\n'
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
    def test_max_rejections_then_allow(self, tmp_path, monkeypatch):
        conv_id = f"chk-limit-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "hello"},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I did some work but did not delegate."}
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        # Write marker file for turn_id = 1
        tracker = os.path.join(str(tmp_path), "cache", f"violation_{conv_id}_1")
        os.makedirs(os.path.dirname(tracker), exist_ok=True)
        with open(tracker + ".json", "w") as f:
            json.dump({"turn_id": 1, "transcript_lines": 1}, f)
    
        for i in range(2):
            result = run_hook(payload)
            assert result.get("decision") == "continue", f"Rejection {i+1} should block"
    
        result = run_hook(payload)
        assert result == {"decision": "allow"}, "Should allow after max rejections"

    def test_allow_if_delegated(self, tmp_path):
        conv_id = f"chk-delegated-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "hello"},
            {
                "source": "MODEL",
                "type": "PLANNER_RESPONSE",
                "tool_calls": [{"name": "invoke_subagent", "args": {}}]
            }
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        tracker = os.path.join(str(tmp_path), "cache", f"violation_{conv_id}_1")
        os.makedirs(os.path.dirname(tracker), exist_ok=True)
        with open(tracker + ".json", "w") as f:
            json.dump({"turn_id": 1, "transcript_lines": 1}, f)
    
        result = run_hook(payload)
        assert result == {"decision": "allow"}

    def test_user_prompt_injection_blocked(self, tmp_path):
        conv_id = f"chk-inject-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {
                "source": "USER",
                "type": "USER_INPUT",
                "tool_calls": [{"name": "invoke_subagent", "args": {}}]
            }
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        tracker = os.path.join(str(tmp_path), "cache", f"violation_{conv_id}_1")
        os.makedirs(os.path.dirname(tracker), exist_ok=True)
        with open(tracker + ".json", "w") as f:
            json.dump({"turn_id": 1, "transcript_lines": 1}, f)
    
        # Should block because the tool call wasn't from MODEL
        for i in range(2):
            result = run_hook(payload)
            assert result.get("decision") == "continue"

    def test_flow_review_question_no_dummy(self, tmp_path):
        # A flow-review question must produce no worker launch
        # if there is no violation.
        conv_id = f"chk-flow-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "USER", "type": "USER_INPUT", "content": "How does this code work?"},
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "It works by parsing."}
        ])
    
        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }
        
        # NO marker file written.
        
        result = run_hook(payload)
        # Should allow immediately because there's no pending violation
        assert result == {"decision": "allow"}
