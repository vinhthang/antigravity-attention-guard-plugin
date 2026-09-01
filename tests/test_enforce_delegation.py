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
            "toolCall": {"args": {"TargetFile": "/some/path/brain/conv-123/task.md"}}
        })
        assert result["decision"] == "allow"

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

    def test_mcp_write_tool_blocked_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "write_file"}}
        })
        assert result["decision"] == "deny"

    def test_mcp_write_tool_allowed_for_subagent(self):
        result = run_hook({
            "modelName": "gemini-3.7-flash-tiered",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "write_file"}}
        })
        assert result["decision"] == "allow"

    def test_mcp_atlassian_write_blocked_for_primary(self):
        """Verify dynamically discovered Atlassian write tools are blocked."""
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "createJiraIssue"}}
        })
        assert result["decision"] == "deny"

    def test_mcp_atlassian_read_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "call_mcp_tool", "args": {"ToolName": "getJiraIssue"}}
        })
        assert result["decision"] == "allow"

