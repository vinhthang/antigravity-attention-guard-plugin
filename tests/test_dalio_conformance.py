#!/usr/bin/env python3
"""
Behavioral Conformance Test Suite for Attention Guard Dalio Alignment.
Verifies role schemas, command validator policies (including P0), AST error suppression, and deployment.
"""
import sys
import os
import io
import ast
import json
import uuid
import importlib
import importlib.util
import pytest

PLUGIN_ROOT = os.path.realpath(os.path.join(os.path.dirname(__file__), ".."))
SCRIPTS_DIR = os.path.join(PLUGIN_ROOT, "scripts")
SCHEMAS_DIR = os.path.join(PLUGIN_ROOT, "schemas")

sys.path.insert(0, SCRIPTS_DIR)
import payload_validator
import command_validator
import deploy_plugin

TEST_UUID = "123e4567-e89b-12d3-a456-426614174000"

class TestSchemas:
    def test_diagnostician_determined_valid(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Root cause identified: unhandled socket timeout in connection pool.",
            "diagnosis": {
                "root_cause_status": "determined",
                "proximate_cause": "TimeoutError: socket timed out on read",
                "root_cause": "Worker thread failed to refresh keep-alive header",
                "evidence": [{
                    "evidence_kind": "source_location",
                    "source_file": "db/pool.py",
                    "line_number": 42,
                    "observation": "Socket timeout set to 0 instead of default 30"
                }],
                "remediation_plan": "Update pool default timeout config"
            }
        }
        ok, err = payload_validator.validate_payload("diagnostician", payload)
        assert ok, f"Expected valid, got error: {err}"

    def test_diagnostician_inconclusive_valid(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Root cause inconclusive: intermittent packet drop.",
            "diagnosis": {
                "root_cause_status": "inconclusive",
                "proximate_cause": "ConnectionResetError: [Errno 54]",
                "evidence": [{
                    "evidence_kind": "command_output",
                    "command": "rtk pytest tests/test_db.py",
                    "observation": "Test failed 1 out of 5 runs without traceback"
                }],
                "competing_hypotheses": [
                    "Host port exhaustion during concurrent test execution",
                    "Flaky upstream database container recycling"
                ],
                "remediation_plan": "Add network isolation mock to test harness"
            }
        }
        ok, err = payload_validator.validate_payload("diagnostician", payload)
        assert ok, f"Expected valid, got error: {err}"

    def test_diagnostician_determined_missing_root_cause_fails(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Root cause determined but missing field.",
            "diagnosis": {
                "root_cause_status": "determined",
                "proximate_cause": "Some proximate cause",
                "evidence": [{"evidence_kind": "source_location", "observation": "test"}],
                "remediation_plan": "some plan"
            }
        }
        ok, err = payload_validator.validate_payload("diagnostician", payload)
        assert not ok, "Expected failure when root_cause is omitted on determined status"

    def test_invalid_uuid_rejected(self):
        payload = {
            "execution_attempt_id": "not-a-valid-uuid",
            "status": "failed",
            "summary": "Valid summary text with invalid UUID.",
            "error_details": {
                "failure_kind": "SHELL_NON_ZERO_EXIT",
                "diagnostic_message": "Failed command"
            }
        }
        ok, err = payload_validator.validate_payload("executor", payload)
        assert not ok, "Expected failure for non-UUID execution_attempt_id"

    def test_executor_success_valid(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Applied file changes and all tests passed.",
            "files_modified": ["src/app.py"],
            "test_results": {
                "passed": 10,
                "failed": 0,
                "total": 10,
                "command_executed": "rtk pytest tests/test_app.py"
            }
        }
        ok, err = payload_validator.validate_payload("executor", payload)
        assert ok, f"Expected valid executor success, got: {err}"

    def test_executor_completed_with_failed_tests_rejected(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Claimed completion despite failed test.",
            "files_modified": ["src/app.py"],
            "test_results": {
                "passed": 9,
                "failed": 1,
                "total": 10,
                "command_executed": "rtk pytest tests/test_app.py"
            }
        }
        ok, err = payload_validator.validate_payload("executor", payload)
        assert not ok, "Executor completed with failed > 0 must be rejected"

    def test_executor_completed_with_error_details_rejected(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Completed with unexpected error_details.",
            "files_modified": ["src/app.py"],
            "test_results": {"passed": 5, "failed": 0, "total": 5, "command_executed": "pytest"},
            "error_details": {"failure_kind": "ASSERTION_FAILURE", "diagnostic_message": "Error"}
        }
        ok, err = payload_validator.validate_payload("executor", payload)
        assert not ok, "Completed executor payload must not contain error_details"

    def test_executor_all_failure_kinds_valid(self):
        kinds = [
            "SHELL_NON_ZERO_EXIT", "PAYLOAD_SCHEMA_VIOLATION",
            "COMMAND_POLICY_VIOLATION", "LIVENESS_TIMEOUT",
            "SYSTEM_SIGNAL", "ASSERTION_FAILURE"
        ]
        for kind in kinds:
            payload = {
                "execution_attempt_id": TEST_UUID,
                "status": "failed",
                "summary": f"Subagent execution failed due to {kind}.",
                "error_details": {
                    "failure_kind": kind,
                    "diagnostic_message": f"Detailed diagnostic message for {kind}."
                }
            }
            ok, err = payload_validator.validate_payload("executor", payload)
            assert ok, f"Failure kind {kind} should be valid, got: {err}"

    def test_coordinator_failure_propagation(self):
        payload = {
            "execution_attempt_id": TEST_UUID,
            "status": "completed",
            "summary": "Claimed completed despite child failure.",
            "subagent_results": [
                {"task_id": "1", "worker_role": "executor", "status": "completed", "summary": "ok"},
                {"task_id": "2", "worker_role": "executor", "status": "failed", "summary": "broken", "advisory": False}
            ]
        }
        ok, err = payload_validator.validate_payload("coordinator", payload)
        assert not ok, "Coordinator completed with failed child must be rejected"

class TestCommandValidator:
    def test_allowed_commands(self):
        ws = PLUGIN_ROOT
        ok, err = command_validator.validate_command("rtk pytest tests/test_dalio_conformance.py", ws)
        assert ok, f"Expected valid command, got: {err}"

        ok, err = command_validator.validate_command("git status", ws)
        assert ok, f"Expected git status valid, got: {err}"

    def test_shell_operators_forbidden(self):
        ws = PLUGIN_ROOT
        for op in ["|", ">", ">>", "<", ";", "&&", "||"]:
            cmd = f"pytest tests/test_dalio_conformance.py {op} cat"
            ok, err = command_validator.validate_command(cmd, ws)
            assert not ok, f"Operator '{op}' should be rejected"

    def test_unauthorized_git_subcommands(self):
        ws = PLUGIN_ROOT
        for subcmd in ["rebase", "reset", "filter-branch", "checkout"]:
            cmd = f"git {subcmd} origin main"
            ok, err = command_validator.validate_command(cmd, ws)
            assert not ok, f"git subcommand '{subcmd}' should be rejected"

    def test_git_push_policy(self):
        ws = PLUGIN_ROOT
        ok, err = command_validator.validate_command("git push origin feat/my-branch", ws)
        assert ok, f"git push to feature branch should be permitted: {err}"

        ok, err = command_validator.validate_command("git push origin main", ws)
        assert not ok, "git push directly to main should be rejected"
        assert "protected branch" in str(err)

        ok, err = command_validator.validate_command("git push origin master", ws)
        assert not ok, "git push directly to master should be rejected"
        assert "protected branch" in str(err)

    def test_destructive_binaries_forbidden(self):
        ws = PLUGIN_ROOT
        for b in ["rm", "chmod"]:
            ok, err = command_validator.validate_command(f"{b} file.txt", ws)
            assert not ok, f"Binary '{b}' should be rejected"
            assert "not in allowed binary whitelist" in str(err)

    def test_p0_security_elevated_deployment_boundary(self):
        ws = PLUGIN_ROOT
        cmd_bad = "cp scripts/deploy_plugin.py ~/.gemini/config/plugins/attention-guard/"
        ok, err = command_validator.validate_command(cmd_bad, ws)
        assert not ok, "Arbitrary command targeting ~/.gemini/config/plugins must be rejected"
        assert "P0 Security Violation" in str(err)

        cmd_good = "python3 scripts/deploy_plugin.py --deploy"
        ok, err = command_validator.validate_command(cmd_good, ws)
        assert ok, f"deploy_plugin.py must be permitted: {err}"

    def test_cross_repo_pytest_allowed(self):
        ws = PLUGIN_ROOT
        cmd = "pytest /Users/thanghoang/github/ai-review-plugin/tests/test_peer_review.py"
        ok, err = command_validator.validate_command(cmd, ws)
        assert ok, f"Cross-repo pytest should be permitted: {err}"

class TestNoBarePassAST:
    def test_ast_no_error_suppression(self):
        for root, _, files in os.walk(SCRIPTS_DIR):
            for file in files:
                if file.endswith(".py"):
                    filepath = os.path.join(root, file)
                    with open(filepath, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=file)
                    
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ExceptHandler):
                            for stmt in node.body:
                                assert not isinstance(stmt, ast.Pass), (
                                    f"VIOLATION: Found bare 'pass' in ExceptHandler in {file} at line {stmt.lineno}"
                                )

class TestDeployPlugin:
    def test_bundle_verification(self):
        ok, missing = deploy_plugin.verify_source_bundle(PLUGIN_ROOT)
        assert ok, f"Source bundle incomplete: missing {missing}"

class TestIdentityAndCommandRemediation:
    def test_p0_identity_inversion_prevention(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
        import ledger
        import common
        importlib.reload(ledger)
        importlib.reload(common)

        l = ledger.Ledger()
        token = str(uuid.uuid4())
        parent_conv_id = "parent-conv-123"
        child_conv_id = "child-conv-456"

        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))

        payload = {
            "token": token,
            "may_delegate": False,
            "remaining_depth": 0,
            "parent_conv_id": parent_conv_id,
            "parent_turn_id": "1"
        }
        l.insert_event(parent_conv_id, "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Execute task\\n\\n[ANTIGRAVITY_TOKEN:{token}]"}}\n'
        )

        parent_data = {
            "conversationId": parent_conv_id,
            "transcriptPath": str(transcript)
        }
        is_sub_parent, _, _, _, _ = common.is_subagent(parent_data)
        assert is_sub_parent is False, "Parent conversation must NOT be recognized as a subagent"

        child_data = {
            "conversationId": child_conv_id,
            "transcriptPath": str(transcript)
        }
        is_sub_child, may_del, depth, p_conv, p_turn = common.is_subagent(child_data)
        assert is_sub_child is True, "Child conversation must be recognized as subagent"
        assert p_conv == parent_conv_id
        assert p_turn == "1"

    def test_subagent_command_validation_enforced(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
        import ledger
        import common
        importlib.reload(ledger)
        importlib.reload(common)

        l = ledger.Ledger()
        token = str(uuid.uuid4())
        parent_conv_id = "parent-conv-123"
        child_conv_id = "child-conv-456"

        with l._get_connection() as conn:
            conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))

        payload = {
            "token": token,
            "may_delegate": False,
            "remaining_depth": 0,
            "parent_conv_id": parent_conv_id,
            "parent_turn_id": "1"
        }
        l.insert_event(parent_conv_id, "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do work\\n\\n[ANTIGRAVITY_TOKEN:{token}]"}}\n'
        )

        spec = importlib.util.spec_from_file_location(
            "enforce_delegation",
            os.path.join(SCRIPTS_DIR, "enforce-delegation.py")
        )
        enforce_mod = importlib.util.module_from_spec(spec)
        sys.modules["enforce_delegation"] = enforce_mod
        spec.loader.exec_module(enforce_mod)

        def run_hook(data):
            stdin = io.StringIO(json.dumps(data))
            stdout = io.StringIO()
            enforce_mod.main(argv=["enforce-delegation.py"], stdin=stdin, stdout=stdout)
            return json.loads(stdout.getvalue().strip())

        # Subagent trying to run forbidden python inline code
        bad_payload_python = {
            "conversationId": child_conv_id,
            "transcriptPath": str(transcript),
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": 'python3 -c "import os"',
                    "Cwd": PLUGIN_ROOT
                }
            }
        }
        result = run_hook(bad_payload_python)
        assert result["decision"] == "deny", f"Expected deny for python3 -c, got: {result}"
        assert "Attention Guard Command Policy Violation" in result.get("reason", "")

        # Subagent trying to run forbidden shell operator
        bad_payload_pipe = {
            "conversationId": child_conv_id,
            "transcriptPath": str(transcript),
            "toolCall": {
                "name": "run_command",
                "args": {
                    "CommandLine": "rtk pytest tests/test_dalio_conformance.py | cat",
                    "Cwd": PLUGIN_ROOT
                }
            }
        }
        result = run_hook(bad_payload_pipe)
        assert result["decision"] == "deny", f"Expected deny for shell operator, got: {result}"
        assert "Attention Guard Command Policy Violation" in result.get("reason", "")


def test_two_tiered_escalation():
    agents_rule_path = os.path.join(PLUGIN_ROOT, "rules", "AGENTS.md")
    assert os.path.exists(agents_rule_path), "rules/AGENTS.md must exist in Attention Guard"
    with open(agents_rule_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Verify rule identity
    assert '<rule name="agent-delegation">' in content

    # Verify Section 1 preservation
    assert "### 1. Subagent Model Selection Framework" in content
    assert "flash_lite" in content

    # Verify Section 2 Two-Tiered Escalation Protocol
    assert "Tier 1: Read-Only Pro Diagnostician" in content
    assert "Tier 2: WorkBuddy External Second-Opinion" in content
    assert "escalation_counter >= 3" in content
    assert 'explicit human approval ("Proceed")' in content

    # Verify Section 3 preservation
    assert "### 3. Subagent Liveness Tracking" in content
    assert 'schedule(DurationSeconds=300' in content

    # Verify Section 4 preservation
    assert "### 4. Subagent Termination Cleanup" in content
