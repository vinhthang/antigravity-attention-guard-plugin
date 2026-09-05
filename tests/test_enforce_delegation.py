#!/usr/bin/env python3
import sys
import os
import io
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from ledger import Ledger
from common import is_subagent

import importlib.util
spec = importlib.util.spec_from_file_location(
    "enforce_delegation",
    os.path.join(os.path.dirname(__file__), "../scripts/enforce-delegation.py")
)
enforce_mod = importlib.util.module_from_spec(spec)
sys.modules["enforce_delegation"] = enforce_mod
spec.loader.exec_module(enforce_mod)

MCP_READ_ALLOWLIST = enforce_mod.MCP_READ_ALLOWLIST
is_artifact_path = enforce_mod.is_artifact_path

@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    # We must patch the DB_PATH within Ledger, but because it's a default kwarg,
    # we just let Ledger instances pick it up via AGY_APP_DATA_DIR.
    # Actually wait, Ledger sets db_path=DB_PATH at module load.
    # Let's monkeypatch Ledger.__init__ to force use of the tmp_path.
    db_path = os.path.join(str(tmp_path), "attention_guard.db")
    
    # We also need to reload ledger to pick up the env var
    import ledger
    importlib.reload(ledger)
    
def run_hook(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    enforce_mod.main(argv=["enforce-delegation.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

class TestSubagentDetection:
    def test_primary_agent_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf /"}
            }
        })
        assert result["decision"] == "deny"
        assert "forbidden from executing shell commands" in result.get("reason", "")

    def test_subagent_with_token_allowed(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        
        token = "1234-abcd"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
        payload = {"token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
        l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:1234-abcd]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6", "conversationId": "child1"}
        assert is_subagent(data) == (True, False, 0, "parent", "1")

    def test_subagent_with_invalid_token_blocked(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:1234-abcd]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6"}
        assert is_subagent(data) == (False, False, 0, None, None)

class TestArtifactPath:
    def test_artifact_path_allowed(self):
        assert is_artifact_path("/home/user/.gemini/antigravity/brain/abc-def-123/plan.md", "/home/user/.gemini/antigravity/brain/abc-def-123") is True

    def test_prefix_escape_blocked(self):
        assert is_artifact_path("/tmp/artifacts-evil/file.py", "/tmp/artifacts") is False

    def test_non_artifact_blocked(self):
        assert is_artifact_path("/Users/code/project/main.py", "/home/user/.gemini/brain/abc") is False

class TestMCPAllowlist:
    def test_mcp_read_allowlist(self):
        assert ("server-filesystem", "read_file") in MCP_READ_ALLOWLIST
        assert ("codegraph", "codegraph_search") in MCP_READ_ALLOWLIST

class TestGenerateImageAllowed:
    def test_generate_image_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "generate_image", "args": {"ImageName": "test_image", "Prompt": "A logo"}}
        })
        assert result["decision"] == "allow"

    def test_subagent_blocked_from_delegating(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        
        token = "1234-abcd"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
        payload = {"token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
        l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:1234-abcd]"}\n')

        data = {
            "transcriptPath": str(transcript),
            "toolCall": {"name": "invoke_subagent"}
        }

        result = run_hook(data)
        assert result.get("decision") == "deny"

class TestCoordinatorDelegation:
    def test_coordinator_can_delegate(self, tmp_path):
        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        
        token = "a1b2c3d4-4321"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
        payload = {"token": token, "may_delegate": True, "remaining_depth": 1, "parent_conv_id": "parent", "parent_turn_id": "1"}
        l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:{token}]"}}\n')

        data = {
            "transcriptPath": str(transcript),
            "toolCall": {"name": "invoke_subagent", "args": {}}
        }

        result = run_hook(data)
        assert result.get("decision") == "allow"
