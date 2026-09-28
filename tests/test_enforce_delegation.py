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


is_artifact_path = enforce_mod.is_artifact_path
is_test_command = enforce_mod.is_test_command

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
    def test_run_command_allowed_for_primary(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rm -rf /"}
            }
        })
        assert result["decision"] == "allow"

    def test_primary_agent_diagnostics_metrics_allowed(self):
        result = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "python3 scripts/diagnostics.py --metrics"}
            }
        })
        assert result["decision"] == "allow"

    def test_primary_agent_write_and_replace_allowed(self):
        res_write = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "/some/repo/file.py", "CodeContent": "print('hello')"}
            }
        })
        assert res_write["decision"] == "allow"

        res_replace = run_hook({
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "replace_file_content",
                "args": {"TargetFile": "/some/repo/file.py", "TargetContent": "a", "ReplacementContent": "b"}
            }
        })
        assert res_replace["decision"] == "allow"

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

    def test_reused_subagent_multiple_turns(self, tmp_path):
        import importlib
        import ledger
        import common
        importlib.reload(ledger)
        importlib.reload(common)
        l = ledger.Ledger()

        token1 = "1111-aaaa"
        token2 = "2222-bbbb"
        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token1,))
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token2,))
        payload1 = {"token": token1, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
        payload2 = {"token": token2, "may_delegate": True, "remaining_depth": 1, "parent_conv_id": "parent", "parent_turn_id": "2"}
        l.insert_event("parent", "1", "PreToolUse", "0", token1, "WORK_PREPARED", json.dumps(payload1))
        l.insert_event("parent", "2", "PreToolUse", "0", token2, "WORK_PREPARED", json.dumps(payload2))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "First task [ANTIGRAVITY_TOKEN:1111-aaaa]"}\n'
            '{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done task 1"}\n'
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Follow-up reused task [ANTIGRAVITY_TOKEN:2222-bbbb]"}\n'
        )
        data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6", "conversationId": "reused_child"}
        # Should detect the most recent token (2222-bbbb) and return its metadata
        assert common.is_subagent(data) == (True, True, 1, "parent", "2")

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

    def test_walkthrough_outside_artifact_dir_blocked(self, tmp_path):
        assert is_artifact_path("/repo/walkthrough.md", str(tmp_path / "artifacts")) is False
        assert is_artifact_path("/repo/walkthrough.md", None) is False

    def test_walkthrough_inside_brain_allowed(self, tmp_path):
        brain_walkthrough = tmp_path / "brain" / "conv-123" / "walkthrough.md"
        assert is_artifact_path(str(brain_walkthrough), None) is True


class TestIsTestCommand:
    def test_search_and_read_commands_not_test_commands(self):
        assert is_test_command("grep pytest .") is False
        assert is_test_command("rg pytest") is False
        assert is_test_command("grep -rn pytest .") is False
        assert is_test_command("which pytest") is False
        assert is_test_command("cat tests/test_pytest.py") is False

    def test_direct_and_python_test_runners(self):
        assert is_test_command("pytest") is True
        assert is_test_command("pytest tests/") is True
        assert is_test_command("rtk pytest tests/") is True
        assert is_test_command("python3 -m pytest tests/") is True
        assert is_test_command("python -m unittest discover") is True
        assert is_test_command("cargo test") is True
        assert is_test_command("npm test") is True



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


class TestSubagentInvocationAllowed:
    def test_invoke_subagent_allowed_for_any_role(self):
        for role in ["Task Executor", "Implementer", "Unit Tester", "Architect"]:
            payload = {
                "modelName": "claude-opus-4.6",
                "toolCall": {
                    "name": "invoke_subagent",
                    "args": {
                        "Subagents": [{"Role": role, "TypeName": "flash", "Prompt": "Do work"}]
                    }
                }
            }
            res = run_hook(payload)
            assert res["decision"] == "allow"

    def test_manage_subagents_unconditional_allowed(self):
        payload = {
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "manage_subagents",
                "args": {"Action": "list"}
            }
        }
        res = run_hook(payload)
        assert res["decision"] == "allow"


class TestPrimaryAgentPlanDelegationEnforcement:
    def test_is_plan_execution_active_helper(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        # Non-existent transcript
        assert enforce_mod.is_plan_execution_active(str(tmp_path / "non_existent.jsonl"), str(tmp_path)) is False

        # No approval
        transcript.write_text('{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Just do a quick fix"}\n')
        assert enforce_mod.is_plan_execution_active(str(transcript), str(tmp_path)) is False

        # Approved via "The user has approved this document"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(tmp_path)) is True

        # Approved via "Proceed on implementation_plan.md"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Proceed on implementation_plan.md"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(tmp_path)) is True

        # Approved but subsequent walkthrough.md present
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
            '{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Generated walkthrough.md successfully"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(tmp_path)) is False

    def test_write_to_file_repo_denied_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        payload = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "/repo/src/core.py",
                    "CodeContent": "def active(): pass"
                }
            }
        }
        res = run_hook(payload)
        assert res["decision"] == "deny"
        assert "Primary Agent is forbidden" in res.get("reason", "") or "Attention Dilution Guard" in res.get("reason", "")

        # Also verify with "Proceed on implementation_plan.md"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Proceed on implementation_plan.md"}\n'
        )
        res = run_hook(payload)
        assert res["decision"] == "deny"

    def test_replace_file_content_repo_denied_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        payload = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "replace_file_content",
                "args": {
                    "TargetFile": "/repo/src/core.py",
                    "TargetContent": "old",
                    "ReplacementContent": "new"
                }
            }
        }
        res = run_hook(payload)
        assert res["decision"] == "deny"

    def test_write_to_file_artifact_allowed_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        # Walkthrough inside artifact_dir
        payload_wt = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(artifact_dir / "walkthrough.md"),
                    "CodeContent": "# Walkthrough"
                }
            }
        }
        assert run_hook(payload_wt)["decision"] == "allow"

        # Other artifact file inside artifact_dir
        payload_other_art = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": str(artifact_dir / "experiment.md"),
                    "CodeContent": "# Experiment"
                }
            }
        }
        assert run_hook(payload_other_art)["decision"] == "allow"

    def test_invoke_subagent_allowed_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        payload = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [{"Role": "Task Executor", "TypeName": "flash", "Prompt": "Implement feature"}]
                }
            }
        }
        assert run_hook(payload)["decision"] == "allow"

    def test_run_command_test_suites_denied_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        test_commands = [
            "rtk pytest tests/",
            "pytest tests/test_enforce_delegation.py",
            "python3 -m pytest tests/",
            "cargo test",
            "npm test"
        ]
        for cmd in test_commands:
            payload = {
                "transcriptPath": str(transcript),
                "artifactDirectoryPath": str(artifact_dir),
                "modelName": "claude-opus-4.6",
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": cmd}
                }
            }
            res = run_hook(payload)
            assert res["decision"] == "deny", f"Expected test command '{cmd}' to be denied during active plan, got {res}"
            assert "Primary Agent is forbidden" in res.get("reason", "") or "Attention Dilution Guard" in res.get("reason", "")

    def test_run_command_read_only_allowed_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        allowed_cmds = [
            "git status",
            "git diff",
            "ls -la",
            "cat README.md"
        ]
        for cmd in allowed_cmds:
            payload = {
                "transcriptPath": str(transcript),
                "artifactDirectoryPath": str(artifact_dir),
                "modelName": "claude-opus-4.6",
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": cmd}
                }
            }
            res = run_hook(payload)
            assert res["decision"] == "allow", f"Expected read-only command '{cmd}' to be allowed, got {res}"

    def test_direct_edits_allowed_when_no_plan_approved(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        # Transcript with no plan approval
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Please fix a minor typo in README.md"}\n'
        )
        # write_to_file on repo file allowed
        payload_write = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "/repo/README.md", "CodeContent": "# New"}
            }
        }
        assert run_hook(payload_write)["decision"] == "allow"

        # replace_file_content on repo file allowed
        payload_replace = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "replace_file_content",
                "args": {"TargetFile": "/repo/README.md", "TargetContent": "a", "ReplacementContent": "b"}
            }
        }
        assert run_hook(payload_replace)["decision"] == "allow"

        # test command allowed for quick one-off
        payload_test = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "rtk pytest tests/"}
            }
        }
        assert run_hook(payload_test)["decision"] == "allow"

    def test_direct_edits_allowed_after_walkthrough_generated(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
            '{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Generated walkthrough.md"}\n'
        )
        payload = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {"TargetFile": "/repo/src/core.py", "CodeContent": "def done(): pass"}
            }
        }
        assert run_hook(payload)["decision"] == "allow"

    def test_tool_outputs_do_not_trigger_plan_approval(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        # Tool output containing "The user has approved this document" must NOT activate plan mode
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Check log files"}\n'
            '{"source": "TOOL_RESULT", "type": "TOOL_OUTPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(artifact_dir)) is False

        # Tool output containing "proceed" must NOT activate plan mode
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Run analysis"}\n'
            '{"source": "TOOL_RESULT", "type": "TOOL_OUTPUT", "content": "Output: proceed with implementation_plan.md"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(artifact_dir)) is False

        # Model output containing approval text must also NOT activate plan mode
        transcript.write_text(
            '{"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "The user has approved this document"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(artifact_dir)) is False

    def test_search_pytest_allowed_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        for search_cmd in ["grep pytest .", "rg pytest", "grep -rn pytest .", "which pytest"]:
            payload = {
                "transcriptPath": str(transcript),
                "artifactDirectoryPath": str(artifact_dir),
                "modelName": "claude-opus-4.6",
                "toolCall": {
                    "name": "run_command",
                    "args": {"CommandLine": search_cmd}
                }
            }
            res = run_hook(payload)
            assert res["decision"] == "allow", f"Search command '{search_cmd}' should be allowed during active plan"

    def test_walkthrough_via_tool_call_deactivates_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
            '{"source": "MODEL", "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "write_to_file", "args": {"TargetFile": "/artifacts/walkthrough.md", "CodeContent": "# Done"}}]}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(artifact_dir)) is False

    def test_tool_output_mentioning_walkthrough_does_not_deactivate_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
            '{"source": "TOOL_RESULT", "type": "TOOL_OUTPUT", "content": "file listing: walkthrough.md"}\n'
        )
        assert enforce_mod.is_plan_execution_active(str(transcript), str(artifact_dir)) is True

    def test_write_to_file_repo_walkthrough_denied_during_active_plan(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        artifact_dir = tmp_path / "artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "The user has approved this document: /artifacts/implementation_plan.md"}\n'
        )
        payload = {
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(artifact_dir),
            "modelName": "claude-opus-4.6",
            "toolCall": {
                "name": "write_to_file",
                "args": {
                    "TargetFile": "/repo/walkthrough.md",
                    "CodeContent": "# Fake walkthrough in workspace repo"
                }
            }
        }
        res = run_hook(payload)
        assert res["decision"] == "deny"

