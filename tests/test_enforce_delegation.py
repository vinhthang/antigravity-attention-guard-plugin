#!/usr/bin/env python3
import sys
import os
import io
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import importlib.util
import json
import pytest
from common import is_subagent, get_cache_dir

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
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        token_file = os.path.join(cache_dir, "agy_issued_token_1234-abcd")
        with open(token_file, "w") as f:
            json.dump({"issuer": "parent", "recipient": None}, f)

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:1234-abcd]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6"}
        assert is_subagent(data) is True

    def test_subagent_with_invalid_token_blocked(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:1234-abcd]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6"}
        assert is_subagent(data) is False


class TestArtifactPath:
    def test_artifact_path_allowed(self):
        assert is_artifact_path("/home/user/.gemini/antigravity/brain/abc-def-123/plan.md", "/home/user/.gemini/antigravity/brain/abc-def-123") is True

    def test_prefix_escape_blocked(self):
        """Paths like /tmp/artifacts-evil/ should NOT match /tmp/artifacts/."""
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
