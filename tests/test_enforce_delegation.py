#!/usr/bin/env python3
import subprocess
import json
import os
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "enforce-delegation.py")


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout)


class TestSubagentDetection:
    def test_flash_model_allowed(self):
        result = run_hook({"modelName": "gemini-2.0-flash", "toolCall": {"args": {}}})
        assert result["decision"] == "allow"

    def test_primary_agent_blocked(self):
        result = run_hook({"modelName": "claude-opus-4.6", "toolCall": {"args": {"TargetFile": "/some/code.py"}}})
        assert result["decision"] == "deny"

    def test_primary_agent_opus_blocked(self):
        result = run_hook({"modelName": "claude-opus-4.6", "toolCall": {"args": {}}})
        assert result["decision"] == "deny"

    def test_subagent_with_marker_allowed(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"type": "USER_INPUT", "content": "Execute task\\n\\n[ANTIGRAVITY_SUBAGENT:conv-123:456]"}\n')
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "transcriptPath": str(transcript),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}
        })
        assert result["decision"] == "allow"

    def test_primary_agent_without_marker_blocked(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"type": "USER_INPUT", "content": "Please write some code"}\n')
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "transcriptPath": str(transcript),
            "toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}
        })
        assert result["decision"] == "deny"


class TestArtifactBypass:
    def test_artifact_path_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "artifactDirectoryPath": "/home/user/.gemini/antigravity/brain/conv-123",
            "toolCall": {"args": {"TargetFile": "/home/user/.gemini/antigravity/brain/conv-123/implementation_plan.md"}}
        })
        assert result["decision"] == "allow"

    def test_brain_path_component_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"args": {"TargetFile": "/some/path/brain/a1b2c3d4-e5f6-7890-abcd-ef1234567890/task.md"}}
        })
        assert result["decision"] == "allow"

    def test_brain_in_project_name_blocked(self):
        """Ensure paths like brain-tumor-classifier don't bypass the guard."""
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"args": {"TargetFile": "/Users/thanghoang/github/brain-tumor-classifier/model.py"}}
        })
        assert result["decision"] == "deny"

    def test_non_artifact_path_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "artifactDirectoryPath": "/home/user/.gemini/antigravity/brain/conv-123",
            "toolCall": {"args": {"TargetFile": "/Users/thanghoang/github/oci/main.tf"}}
        })
        assert result["decision"] == "deny"


class TestSecurityBypass:
    def test_flash_in_command_not_bypass(self):
        """C-01 regression: 'flash' in command args should NOT bypass if modelName is not flash."""
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git commit -m 'fix flash bug'"}}
        })
        assert result["decision"] == "deny"

    def test_brain_in_command_not_bypass(self):
        """C-01 regression: 'brain/' in command args should NOT bypass for run_command."""
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /brain/data"}}
        })
        assert result["decision"] == "deny"


class TestEdgeCases:
    def test_empty_payload(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="",
            capture_output=True, text=True, timeout=5
        )
        output = json.loads(result.stdout)
        assert output["decision"] == "allow"

    def test_malformed_json(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="not valid json",
            capture_output=True, text=True, timeout=5
        )
        output = json.loads(result.stdout)
        assert output["decision"] == "allow"


class TestMCPToolCoverage:
    def test_mcp_read_tool_allowed_for_subagent(self):
        result = run_hook({
            "modelName": "gemini-3.7-flash-tiered",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "read_file"}}
        })
        assert result["decision"] == "allow"

    def test_mcp_read_tool_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "read_file"}}
        })
        assert result["decision"] == "allow"

    def test_mcp_write_tool_allowed_for_subagent(self):
        result = run_hook({
            "modelName": "gemini-3.7-flash-tiered",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "write_file"}}
        })
        assert result["decision"] == "allow"

    def test_mcp_atlassian_read_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "getJiraIssue"}}
        })
        assert result["decision"] == "allow"


class TestSQLiteProtobufDetection:
    def test_pro_subagent_with_field_5_allowed(self):
        import uuid
        import sqlite3

        test_id = f"test-subagent-{uuid.uuid4()}"
        db_dir = os.path.expanduser("~/.gemini/antigravity/conversations")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, f"{test_id}.db")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE trajectory_metadata_blob (id TEXT PRIMARY KEY, data BLOB);")
                # Field 5 wire format: (5<<3)|2 = 0x2a ('*'), length 0x04, payload b'test'
                conn.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)", (b"\x2a\x04test",))

            result = run_hook({
                "conversationId": test_id,
                "modelName": "claude-opus-4.6",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}
            })
            assert result["decision"] == "allow"
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_primary_agent_on_flash_blocked(self):
        import uuid
        import sqlite3

        test_id = f"test-primary-{uuid.uuid4()}"
        db_dir = os.path.expanduser("~/.gemini/antigravity/conversations")
        os.makedirs(db_dir, exist_ok=True)
        db_path = os.path.join(db_dir, f"{test_id}.db")

        try:
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE trajectory_metadata_blob (id TEXT PRIMARY KEY, data BLOB);")
                # Field 1 wire format (no Field 5)
                conn.execute("INSERT INTO trajectory_metadata_blob VALUES ('main', ?)", (b"\x08\x01",))

            result = run_hook({
                "conversationId": test_id,
                "modelName": "gemini-2.0-flash",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "touch /tmp/bad"}}
            })
            assert result["decision"] == "deny"
        finally:
            if os.path.exists(db_path):
                os.remove(db_path)

    def test_missing_db_fallback_flash_allowed(self):
        result = run_hook({
            "conversationId": "non-existent-conv-id",
            "modelName": "gemini-2.0-flash",
            "toolCall": {"args": {}}
        })
        assert result["decision"] == "allow"

    def test_missing_db_fallback_pro_blocked(self):
        result = run_hook({
            "conversationId": "non-existent-conv-id",
            "modelName": "claude-opus-4.6",
            "toolCall": {"args": {"TargetFile": "/some/code.py"}}
        })
        assert result["decision"] == "deny"

    def test_brain_index_db_detection(self):
        import sqlite3

        brain_dir = os.path.expanduser("~/.gemini/antigravity/brain")
        os.makedirs(brain_dir, exist_ok=True)
        index_db = os.path.join(brain_dir, "index.db")
        created = False

        try:
            if not os.path.exists(index_db):
                created = True
                with sqlite3.connect(index_db) as conn:
                    conn.execute("CREATE TABLE trajectory_metadata (conversation_id TEXT PRIMARY KEY, data BLOB);")
                    conn.execute("INSERT INTO trajectory_metadata VALUES (?, ?)", ("index-sub-1", b"\x2a\x04test"))

            result = run_hook({
                "conversationId": "index-sub-1",
                "modelName": "claude-opus-4.6",
                "toolCall": {"name": "run_command", "args": {"CommandLine": "ls"}}
            })
            assert result["decision"] == "allow"
        finally:
            if created and os.path.exists(index_db):
                os.remove(index_db)



