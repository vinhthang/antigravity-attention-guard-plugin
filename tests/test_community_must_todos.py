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
from common import validate_no_raw_log_dump

# Dynamically load scripts with hyphens in file names
def _load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SCRIPTS_DIR, filename))
    if spec and spec.loader:
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    return None

enforce_mod = _load_module("enforce_delegation", "enforce-delegation.py")
inject_mod = _load_module("inject_rules", "inject-rules.py")


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
