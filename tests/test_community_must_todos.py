#!/usr/bin/env python3
"""
Unit and integration tests for Community & Literature Must-To-Do Hardening:
- REQ-007: Antigravity 2.0 Tool & Argument Schema Parity
- REQ-008: Mechanical Test-Tampering Guard
- REQ-009: Subagent Doom-Loop Circuit Breaker
- REQ-010: Mechanical Destructive Command Guard
- REQ-011: Dynamic Context Budget Status Gauge & Pre-Compaction Checkpoint
- REQ-012: Observation Masking / Raw Terminal Dump Guard
- REQ-013: Turn-Scoped Walkthrough Freshness Verification
"""
import importlib.util
import io
import json
import os
import sys
import time
import uuid
from pathlib import Path
import pytest

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from ledger import Ledger
from payload_validator import (
    validate_payload,
    validate_payload_builtin,
    validate_no_raw_log_dump,
)
# Dynamically load scripts with hyphens in file names
def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS_DIR, filename))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    return None

attention_check = _load_module("attention_check", "attention-check.py")
check_walkthrough_requirement = getattr(attention_check, "check_walkthrough_requirement", None)

attention_refresh = _load_module("attention_refresh", "attention-refresh.py")
build_refresh_reminder = getattr(attention_refresh, "build_refresh_reminder", None)

enforce_mod = _load_module("enforce_delegation", "enforce-delegation.py")
inject_mod = _load_module("inject_rules", "inject-rules.py")


# ============================================================================
# REQ-011: Dynamic Context Budget Status Gauge & Pre-Compaction Checkpoint
# ============================================================================

class TestContextBudgetTelemetryAndCheckpoint:
    @pytest.fixture
    def ledger(self, tmp_path):
        db_path = str(tmp_path / "test_ledger.db")
        return Ledger(db_path=db_path)

    def test_build_refresh_reminder_telemetry_gauge(self, tmp_path, ledger):
        conv_id = "test-conv-telemetry"
        total_tokens = 32000
        reminder = build_refresh_reminder(
            conv_id,
            total_tokens=total_tokens,
            token_budget=128000,
            app_data_dir=str(tmp_path),
            ledger=ledger,
        )

        assert "⚡ Attention Guard Reminder" in reminder
        assert "[Context Telemetry: ~32,000 tokens (25.0% of 128k budget) | Workers: 0]" in reminder
        # Threshold not reached, checkpoint should not be created
        checkpoint_file = tmp_path / "brain" / conv_id / "session_checkpoint.md"
        assert not checkpoint_file.exists()

    def test_build_refresh_reminder_pre_compaction_checkpoint(self, tmp_path, ledger):
        conv_id = "test-conv-checkpoint"
        total_tokens = 95000
        artifact_dir = str(tmp_path / "custom_artifacts")

        reminder = build_refresh_reminder(
            conv_id,
            total_tokens=total_tokens,
            token_budget=128000,
            checkpoint_threshold=80000,
            artifact_dir=artifact_dir,
            ledger=ledger,
        )

        assert "[Context Telemetry: ~95,000 tokens (74.2% of 128k budget) | Workers: 0]" in reminder
        assert "⚠️ Context Threshold Reached" in reminder
        assert "session_checkpoint.md" in reminder

        checkpoint_file = Path(artifact_dir) / "session_checkpoint.md"
        assert checkpoint_file.is_file()
        content = checkpoint_file.read_text(encoding="utf-8")
        assert "# Session State Checkpoint (Pre-Compaction Preservation)" in content
        assert "Context Tokens: ~95,000" in content
        assert "Compaction Preservation Notice" in content

    def test_build_refresh_reminder_with_prepared_workers(self, ledger):
        conv_id = "conv-workers-audit"
        token_a, token_b = str(uuid.uuid4()), str(uuid.uuid4())
        ledger.insert_event(conv_id, "1", "PreToolUse", "0", token_a, "WORK_PREPARED", json.dumps({"token": token_a}))
        ledger.insert_event(conv_id, "1", "PreToolUse", "1", token_b, "WORK_PREPARED", json.dumps({"token": token_b}))

        reminder = build_refresh_reminder(conv_id, total_tokens=40000, ledger=ledger)
        assert "Workers: 2" in reminder

    def test_build_refresh_reminder_overload_signatures(self, tmp_path, ledger):
        # 1. Positional overload: (session_id, total_tokens, ledger, conv_id, artifact_dir)
        art_dir = str(tmp_path / "pos_art")
        r1 = build_refresh_reminder("sess-1", 85000, ledger, "conv-pos", art_dir)
        assert "[Context Telemetry: ~85,000 tokens" in r1
        assert (Path(art_dir) / "session_checkpoint.md").exists()

        # 2. Keyword overload: conv_id, *, token_budget=..., checkpoint_threshold=...
        r2 = build_refresh_reminder(
            "conv-kw",
            token_budget=100000,
            checkpoint_threshold=50000,
            total_tokens=60000,
            artifact_dir=art_dir,
            ledger=ledger,
        )
        assert "(60.0% of 100k budget)" in r2


# ============================================================================
# REQ-012: Observation Masking / Raw Terminal Dump Guard
# ============================================================================

class TestObservationMaskingGuard:
    def test_validate_no_raw_log_dump_ansi_escape(self):
        summary_ansi = "The command failed with \x1b[31merror: stack overflow\x1b[0m in worker."
        ok, err = validate_no_raw_log_dump(summary_ansi)
        assert not ok
        assert "ANSI escape sequence" in (err or "")

    def test_validate_no_raw_log_dump_traceback_frames(self):
        summary_tb = (
            'Traceback details:\n'
            '  File "module/core.py", line 12, in start\n'
            '  File "module/runner.py", line 45, in run\n'
            '  File "module/worker.py", line 98, in execute\n'
            '  File "module/handler.py", line 150, in handle\n'
            'Fatal: recursion limit exceeded.'
        )
        ok, err = validate_no_raw_log_dump(summary_tb)
        assert not ok
        assert "traceback frames detected" in (err or "")

        # 3 frames should be allowed (under the 4-frame threshold)
        summary_tb_3 = (
            'Traceback details:\n'
            '  File "module/core.py", line 12, in start\n'
            '  File "module/runner.py", line 45, in run\n'
            '  File "module/worker.py", line 98, in execute\n'
            'Failed.'
        )
        ok3, err3 = validate_no_raw_log_dump(summary_tb_3)
        assert ok3
        assert err3 is None

    def test_validate_no_raw_log_dump_large_pytest_dump(self):
        large_dump = "=== test session starts ===\n" + ("x" * 2100)
        ok, err = validate_no_raw_log_dump(large_dump)
        assert not ok
        assert "=== test session starts ===" in (err or "")

        # Short pytest dump (<= 2000 chars) is permitted
        short_dump = "=== test session starts ===\nplatform darwin\ncollected 2 items\n2 passed"
        ok_short, err_short = validate_no_raw_log_dump(short_dump)
        assert ok_short
        assert err_short is None

    def test_validate_payload_enforces_no_raw_log_dump(self):
        test_uuid = str(uuid.uuid4())
        payload = {
            "execution_attempt_id": test_uuid,
            "status": "completed",
            "summary": "Ran tests: \x1b[32mPASSED\x1b[0m all 10 checks.",
            "files_modified": ["src/app.py"],
            "test_results": {"passed": 10, "failed": 0, "total": 10, "command_executed": "pytest"}
        }

        ok, err = validate_payload("executor", payload)
        assert not ok
        assert "ANSI escape sequence" in (err or "")

        ok_builtin, err_builtin = validate_payload_builtin("executor", payload)
        assert not ok_builtin
        assert "ANSI escape sequence" in (err_builtin or "")

    def test_clean_summary_passes_validation(self):
        test_uuid = str(uuid.uuid4())
        payload = {
            "execution_attempt_id": test_uuid,
            "status": "completed",
            "summary": "Completed feature implementation with comprehensive unit and regression tests passing cleanly.",
            "files_modified": ["src/app.py"],
            "test_results": {"passed": 5, "failed": 0, "total": 5, "command_executed": "pytest"}
        }

        ok, err = validate_payload("executor", payload)
        assert ok, f"Clean summary rejected: {err}"


# ============================================================================
# REQ-013: Turn-Scoped Walkthrough Freshness Verification
# ============================================================================

class TestWalkthroughFreshnessVerification:
    def test_check_walkthrough_requirement_missing(self, tmp_path):
        payload = {"artifactDirectoryPath": str(tmp_path)}
        assert not check_walkthrough_requirement(payload, "conv-1")

    def test_check_walkthrough_requirement_empty(self, tmp_path):
        payload = {"artifactDirectoryPath": str(tmp_path)}
        (tmp_path / "walkthrough.md").write_text("")
        assert not check_walkthrough_requirement(payload, "conv-1")

    def test_check_walkthrough_requirement_stale_mtime(self, tmp_path):
        payload = {"artifactDirectoryPath": str(tmp_path)}
        target = tmp_path / "walkthrough.md"
        target.write_text("# Walkthrough content\n")

        # Set file mtime to 100.0
        os.utime(target, (100.0, 100.0))

        # Turn subagents started at 120.0 (stale by 20s, exceeds 5s clock tolerance)
        assert not check_walkthrough_requirement(payload, "conv-1", min_mtime=120.0)

    def test_check_walkthrough_requirement_fresh_mtime(self, tmp_path):
        payload = {"artifactDirectoryPath": str(tmp_path)}
        target = tmp_path / "walkthrough.md"
        target.write_text("# Walkthrough content updated\n")

        # Set file mtime to 118.0
        os.utime(target, (118.0, 118.0))

        # Turn subagents started at 120.0 (within 5s tolerance: 118.0 >= 120.0 - 5.0)
        assert check_walkthrough_requirement(payload, "conv-1", min_mtime=120.0)

        # Truly newer mtime (125.0 > 120.0)
        os.utime(target, (125.0, 125.0))
        assert check_walkthrough_requirement(payload, "conv-1", min_mtime=120.0)

    def test_attention_check_turn_scoped_mtime_query(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "attention_guard.db")
        monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
        l = Ledger(db_path=db_path)

        conv_id = "conv-freshness-test"
        turn_id = "1"
        now = time.time()

        # Insert completed work item with created_at = now - 60
        work_time = now - 60.0
        with l._get_connection() as conn:
            conn.execute(
                "INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id) "
                "VALUES (?, 'COMPLETED', ?, ?, ?, ?)",
                ("worker-1", work_time, now, conv_id, turn_id),
            )

        # Transition FSM to EXECUTION_ACTIVE
        l.insert_event(conv_id, turn_id, "PreToolUse", "0", "invoke", "WORK_PREPARED", json.dumps({"tool": "invoke"}))
        l.insert_event(conv_id, turn_id, "PostToolUse", "0", "invoke", "HANDOFF_ACCEPTED", json.dumps({}))

        art_dir = tmp_path / "brain" / conv_id
        art_dir.mkdir(parents=True)
        wt = art_dir / "walkthrough.md"

        # 1. Stale walkthrough (mtime before work started: work_time - 30)
        wt.write_text("# Old walkthrough")
        os.utime(wt, (work_time - 30.0, work_time - 30.0))

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            json.dumps({"source": "USER", "type": "USER_INPUT", "content": "build feature", "step_index": 1}) + "\n"
            + json.dumps({"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done."}) + "\n"
        )

        payload = {
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "artifactDirectoryPath": str(art_dir),
            "fullyIdle": True,
            "terminationReason": "model_stop",
        }

        # Stale walkthrough should trigger rejection ("decision": "continue")
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        attention_check.main(stdin=stdin, stdout=stdout)
        res = json.loads(stdout.getvalue().strip())
        assert res.get("decision") == "continue"

        # 2. Fresh walkthrough (mtime updated during or after turn work: work_time + 10)
        os.utime(wt, (work_time + 10.0, work_time + 10.0))
        stdin = io.StringIO(json.dumps(payload))
        stdout = io.StringIO()
        attention_check.main(stdin=stdin, stdout=stdout)
        res2 = json.loads(stdout.getvalue().strip())
        assert res2.get("decision") == "allow"


# ============================================================================
# REQ-007, REQ-008, REQ-009, REQ-010: Parallel Worker Integration Tests
# ============================================================================

class TestAntigravity2ToolParity:
    """REQ-007: Antigravity 2.0 tool schema parity (write_file/edit_file with Path, flat invoke_subagent)."""

    def test_extract_target_file_parity(self):
        extract_fn = getattr(enforce_mod, "extract_target_file", getattr(enforce_mod, "_extract_target_file", None))
        assert extract_fn is not None
        assert extract_fn({"Path": "/abs/file.py"}) == "/abs/file.py"
        assert extract_fn({"TargetFile": "/abs/legacy.py"}) == "/abs/legacy.py"
        assert extract_fn({"target_file": "/abs/snake.py"}) == "/abs/snake.py"
        assert extract_fn({"file_path": "/abs/fp.py"}) == "/abs/fp.py"
        assert extract_fn({"path": "/abs/p.py"}) == "/abs/p.py"

    def test_flat_invoke_subagent_extraction(self):
        extract_sa = getattr(inject_mod, "extract_subagents", None)
        assert extract_sa is not None
        # List format
        res_list = extract_sa({"Subagents": [{"Prompt": "do work", "Role": "Worker"}]})
        assert len(res_list) == 1
        assert res_list[0]["Prompt"] == "do work"
        # Flat format
        res_flat = extract_sa({"Prompt": "do work flat", "Role": "Worker", "TypeName": "WorkerAgent"})
        assert len(res_flat) == 1
        assert res_flat[0]["Prompt"] == "do work flat"


class TestTestTamperingGuard:
    """REQ-008: Mechanical Test-Tampering Guard."""

    def test_check_test_tampering(self):
        check_fn = getattr(enforce_mod, "check_test_tampering", None)
        assert check_fn is not None

        # Skip marker added to test file -> Denied
        args_skip = {"Path": "tests/test_feature.py", "Replacement": "def test_foo():\n    pytest.skip('bypassed')"}
        reason = check_fn("tests/test_feature.py", args_skip)
        assert reason is not None
        assert "test-skipping marker" in reason.lower() or "tampering" in reason.lower()

        # assert True added to test file -> Denied
        args_assert = {"Path": "tests/test_feature.py", "Replacement": "def test_foo():\n    assert True"}
        reason_assert = check_fn("tests/test_feature.py", args_assert)
        assert reason_assert is not None

        # Safe edit on test file -> Allowed
        args_safe = {"Path": "tests/test_feature.py", "Replacement": "def test_foo():\n    assert result == 42"}
        assert check_fn("tests/test_feature.py", args_safe) is None

        # Edits on non-test files -> Allowed
        args_non_test = {"Path": "src/feature.py", "Replacement": "# pytest.skip comment in source"}
        assert check_fn("src/feature.py", args_non_test) is None

    def test_test_tampering_env_var_override(self, monkeypatch):
        monkeypatch.setenv("AGY_ALLOW_TEST_SKIP", "1")
        check_fn = getattr(enforce_mod, "check_test_tampering", None)
        assert check_fn is not None
        args_skip = {"Path": "tests/test_feature.py", "Replacement": "def test_foo():\n    pytest.skip('bypassed')"}
        assert check_fn("tests/test_feature.py", args_skip) is None


class TestSubagentDoomLoopCircuitBreaker:
    """REQ-009: Subagent Doom-Loop Circuit Breaker."""

    def test_subagent_doom_loop_detection(self, tmp_path):
        check_fn = getattr(enforce_mod, "check_subagent_doom_loop", None)
        assert check_fn is not None

        db_path = str(tmp_path / "doom_loop.db")
        l = Ledger(db_path=db_path)
        conv_id = "sub-doom-1"
        turn_id = "1"
        cmd_args = {"CommandLine": "pytest tests/failing_test.py"}

        # 1st run -> Allowed
        assert check_fn(l, conv_id, turn_id, "run_command", cmd_args) is None
        # 2nd run -> Allowed
        assert check_fn(l, conv_id, turn_id, "run_command", cmd_args) is None
        # 3rd identical run without file edit -> Denied
        reason = check_fn(l, conv_id, turn_id, "run_command", cmd_args)
        assert reason is not None
        assert "doom-loop" in reason.lower() or "circuit breaker" in reason.lower()


class TestDestructiveCommandGuard:
    """REQ-010: Mechanical Destructive Command Guard."""

    def test_check_destructive_command(self):
        check_fn = getattr(enforce_mod, "check_destructive_command", None)
        assert check_fn is not None

        destructive = [
            "git reset --hard",
            "git reset --hard HEAD~1",
            "git clean -fd",
            "git clean -f",
            "git clean -fx",
            "git checkout -- .",
            "git restore .",
            "git push origin main --force",
            "git push -f origin main",
            "rm -rf /",
            "rm -rf .git",
        ]
        for cmd in destructive:
            reason = check_fn(cmd)
            assert reason is not None, f"Expected destructive command to be blocked: {cmd}"

        safe = [
            "git status",
            "git diff",
            "git checkout -b feat/new-work",
            "git restore src/specific_file.py",
            "git push --force-with-lease origin main",
            "pytest tests/test_app.py",
            "rm -rf /tmp/scratch_123",
        ]
        for cmd in safe:
            assert check_fn(cmd) is None, f"Expected safe command to be allowed: {cmd}"
