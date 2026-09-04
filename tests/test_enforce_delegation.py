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
WRITE_VERB_PREFIXES = enforce_mod.WRITE_VERB_PREFIXES
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
    def test_flash_model_allowed_no_transcript(self):
        """Flash model without transcript should be treated as subagent."""
        result = run_hook({"modelName": "gemini-2.0-flash", "toolCall": {"args": {}}})
        assert result["decision"] == "allow"

    def test_primary_agent_blocked(self):
        result = run_hook({"modelName": "claude-opus-4.6", "toolCall": {"args": {"TargetFile": "/some/code.py"}}})
        assert result["decision"] == "deny"

    def test_subagent_with_marker_in_user_input_allowed(self, tmp_path):
        """Real Antigravity transcripts record the injected prompt as USER_INPUT.
        The marker should still be detected via raw byte scanning."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_SUBAGENT:abc:123]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6"}
        assert is_subagent(data) is True

    def test_conversation_id_tracking_blocks_primary(self, tmp_path):
        """A conversationId recorded as primary should be blocked."""
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        primary_file = os.path.join(cache_dir, "agy_primary_conv-primary-123")
        with open(primary_file, "w") as f:
            f.write("1234567890")
        data = {"conversationId": "conv-primary-123", "modelName": "claude-opus-4.6"}
        assert is_subagent(data) is False

    def test_unknown_conversation_id_with_marker_allowed(self, tmp_path):
        """Unknown conversationId with marker in transcript should be allowed."""
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "[ANTIGRAVITY_SUBAGENT:abc:123]"}\n'
        )
        data = {"conversationId": "conv-subagent-456", "transcriptPath": str(transcript)}
        assert is_subagent(data) is True

    def test_multi_level_delegation_subagent_takes_precedence(self, tmp_path):
        """A middle-tier agent (has marker AND has primary cache) should be treated as subagent."""
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        # Create primary cache file for this conversation
        primary_file = os.path.join(cache_dir, "agy_primary_mid-tier-conv")
        with open(primary_file, "w") as f:
            f.write("1234567890")
        # Create transcript with marker
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do task\\n\\n[ANTIGRAVITY_SUBAGENT:parent:123]"}\n'
        )
        data = {"conversationId": "mid-tier-conv", "transcriptPath": str(transcript)}
        assert is_subagent(data) is True  # Marker takes precedence over primary cache

    def test_flash_with_transcript_no_marker_blocked(self, tmp_path):
        """Flash model WITH transcript but no marker should be blocked."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "hello"}\n')
        data = {"transcriptPath": str(transcript), "modelName": "gemini-2.0-flash"}
        assert is_subagent(data) is False

    def test_model_name_fallback_no_transcript(self):
        assert is_subagent({"modelName": "gemini-2.0-flash"}) is True
        assert is_subagent({"modelName": "gemini-2.0-flash-lite"}) is True
        assert is_subagent({"modelName": "claude-3-5-sonnet"}) is False
        assert is_subagent({}) is False


class TestArtifactPath:
    def test_artifact_path_allowed(self):
        assert is_artifact_path("/home/user/.gemini/antigravity/brain/abc-def-123/plan.md", "/home/user/.gemini/antigravity/brain/abc-def-123") is True

    def test_prefix_escape_blocked(self):
        """Paths like /tmp/artifacts-evil/ should NOT match /tmp/artifacts/."""
        assert is_artifact_path("/tmp/artifacts-evil/file.py", "/tmp/artifacts") is False

    def test_non_artifact_blocked(self):
        assert is_artifact_path("/Users/code/project/main.py", "/home/user/.gemini/brain/abc") is False


class TestWriteVerbPrefixes:
    def test_write_verbs_present(self):
        expected_verbs = [
            "write", "edit", "create", "update", "delete", "remove",
            "push", "move", "fork", "insert", "modify", "set", "put",
            "patch", "deploy", "add", "transition", "fill",
            "merge", "submit", "approve", "publish", "archive", "send", "commit", "upload",
        ]
        for verb in expected_verbs:
            assert verb in WRITE_VERB_PREFIXES


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
