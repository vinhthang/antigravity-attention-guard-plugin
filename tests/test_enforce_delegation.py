#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
import importlib.util
import json
import subprocess
import pytest
from common import is_subagent, get_cache_dir

spec = importlib.util.spec_from_file_location(
    "enforce_delegation",
    os.path.join(os.path.dirname(__file__), "../scripts/enforce-delegation.py")
)
enforce_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enforce_mod)
MCP_READ_ALLOWLIST = enforce_mod.MCP_READ_ALLOWLIST
is_artifact_path = enforce_mod.is_artifact_path

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "enforce-delegation.py")


@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5,
        env={**os.environ}
    )
    return json.loads(result.stdout)


class TestSubagentDetection:
    def test_primary_agent_blocked(self):
        result = run_hook({"modelName": "claude-opus-4.6", "toolCall": {"args": {"TargetFile": "/some/code.py"}}})
        assert result["decision"] == "deny"

    def test_subagent_with_token_allowed(self, tmp_path):
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        token_file = os.path.join(cache_dir, "agy_issued_token_1234-abcd")
        with open(token_file, "w") as f:
            f.write("parent")
            
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
        assert "read_file" in MCP_READ_ALLOWLIST
        assert "codegraph_search" in MCP_READ_ALLOWLIST



class TestGenerateImageAllowed:
    def test_generate_image_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "generate_image", "args": {"ImageName": "test_image", "Prompt": "A logo"}}
        })
        assert result["decision"] == "allow"


class TestPrimarySafeCommands:
    def test_git_status_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git status"}}
        })
        assert result["decision"] == "allow"

    def test_git_log_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "git log -n 5 --oneline"}}
        })
        assert result["decision"] == "allow"

    def test_rg_search_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rg 'pattern' src/"}}
        })
        assert result["decision"] == "allow"

    def test_grep_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "grep -r 'TODO' ."}}
        })
        assert result["decision"] == "allow"

    def test_ls_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "ls -la"}}
        })
        assert result["decision"] == "allow"

    def test_tree_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "tree src/"}}
        })
        assert result["decision"] == "allow"

    def test_echo_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "echo hello"}}
        })
        assert result["decision"] == "allow"

    def test_kubectl_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "kubectl logs pod-1"}}
        })
        assert result["decision"] == "deny"

    def test_docker_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "docker exec -it container bash"}}
        })
        assert result["decision"] == "deny"

    def test_mvn_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "mvn clean install"}}
        })
        assert result["decision"] == "deny"

    def test_rm_blocked(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rm -rf /tmp/test"}}
        })
        assert result["decision"] == "deny"

    def test_pytest_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "pytest tests/ -v"}}
        })
        assert result["decision"] == "allow"

    def test_rtk_prefixed_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk kubectl get pods"}}
        })
        assert result["decision"] == "allow"

    def test_safe_with_env_vars(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {"name": "run_command", "args": {"CommandLine": "RUST_LOG=debug git status"}}
        })
        assert result["decision"] == "allow"
