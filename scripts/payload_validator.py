#!/usr/bin/env python3
"""
Zero-dependency Payload Validator for Attention Guard Subagent Data Contracts.
Validates diagnostician, executor, and coordinator JSON payloads against Draft-07 schemas.
Uses jsonschema if available; falls back to robust built-in validation using standard library.
"""
import sys
import os
import json
import uuid
import argparse
import re
from typing import Tuple, Optional, Dict, Any

SCHEMAS_DIR = os.path.realpath(os.path.join(os.path.dirname(__file__), "..", "schemas"))

ROLE_SCHEMA_MAP = {
    "diagnostician": "diagnostician-payload.json",
    "executor": "executor-payload.json",
    "coordinator": "coordinator-payload.json",
}

def validate_uuid(val: Any) -> bool:
    try:
        uuid.UUID(str(val))
        return True
    except (ValueError, TypeError, AttributeError):
        return False

def validate_causal_attribution(diag: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    has_attributions = "edit_attributions" in diag
    has_lesson = "transferable_lesson" in diag

    if has_attributions:
        attributions = diag["edit_attributions"]
        if not isinstance(attributions, list):
            return False, "'edit_attributions' must be an array"
        for idx, item in enumerate(attributions):
            if not isinstance(item, dict):
                return False, f"Item {idx} in 'edit_attributions' must be an object"
            for req in ["component", "change", "observed_divergence", "verdict"]:
                if req not in item:
                    return False, f"Item {idx} in 'edit_attributions' missing required field: '{req}'"
            if not isinstance(item["component"], str) or len(item["component"]) < 1:
                return False, f"Item {idx} 'component' must be non-empty string"
            if not isinstance(item["change"], str) or len(item["change"]) < 5:
                return False, f"Item {idx} 'change' must be at least 5 chars"
            if not isinstance(item["observed_divergence"], str) or len(item["observed_divergence"]) < 5:
                return False, f"Item {idx} 'observed_divergence' must be at least 5 chars"
            valid_verdicts = ("helped", "hurt", "no_observed_effect", "confounded")
            if item["verdict"] not in valid_verdicts:
                return False, f"Item {idx} 'verdict' must be one of {valid_verdicts}, got '{item['verdict']}'"

    if has_lesson:
        lesson = diag["transferable_lesson"]
        if not isinstance(lesson, dict):
            return False, "'transferable_lesson' must be an object"
        for req in ["cue", "lesson", "evidence", "confidence"]:
            if req not in lesson:
                return False, f"'transferable_lesson' missing required field: '{req}'"
        for fld in ["cue", "lesson", "evidence"]:
            if not isinstance(lesson[fld], str) or len(lesson[fld]) < 10:
                return False, f"'transferable_lesson' field '{fld}' must be at least 10 chars"
        valid_conf = ("high", "medium", "low")
        if lesson["confidence"] not in valid_conf:
            return False, f"'transferable_lesson' 'confidence' must be one of {valid_conf}, got '{lesson['confidence']}'"

    # Confounding Guard: If transferable_lesson and edit_attributions are both present
    if has_lesson and has_attributions:
        attributions = diag["edit_attributions"]
        if not isinstance(attributions, list) or len(attributions) == 0:
            return False, "Confounded edit attributions cannot support a transferable_lesson: at least one isolated 'helped' or 'hurt' verdict is required"
        has_isolated = any(
            isinstance(item, dict) and item.get("verdict") in ("helped", "hurt")
            for item in attributions
        )
        if not has_isolated:
            return False, "Confounded edit attributions cannot support a transferable_lesson: at least one isolated 'helped' or 'hurt' verdict is required"

    return True, None

def validate_no_raw_log_dump(summary: str) -> Tuple[bool, Optional[str]]:
    """Reject raw ANSI escape codes or multi-line terminal/traceback dumps in summary (REQ-012)."""
    if not isinstance(summary, str):
        return True, None

    if "\x1b[" in summary:
        return False, "Raw terminal log dump forbidden in summary: ANSI escape sequence ('\\x1b[') detected"

    tb_matches = re.findall(r'File\s+"[^"]+",\s+line\s+\d+', summary)
    if len(tb_matches) >= 4:
        return False, f"Raw terminal log dump forbidden in summary: {len(tb_matches)} traceback frames detected"

    if len(summary) > 2000 and "=== test session starts ===" in summary:
        return False, "Raw terminal log dump forbidden in summary: raw '=== test session starts ===' dump exceeding 2,000 characters"

    return True, None

def validate_payload_builtin(role: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    if not isinstance(payload, dict):
        return False, "Payload must be a JSON object"
    
    for req in ["execution_attempt_id", "status", "summary"]:
        if req not in payload:
            return False, f"Missing required field: '{req}'"
    
    if not validate_uuid(payload["execution_attempt_id"]):
        return False, f"Invalid execution_attempt_id format: expected UUID, got {payload['execution_attempt_id']}"
    
    status = payload["status"]
    if status not in ("completed", "failed"):
        return False, f"Invalid status: '{status}'. Expected 'completed' or 'failed'"
    
    summary = payload["summary"]
    if not isinstance(summary, str) or len(summary) < 10:
        return False, f"Invalid summary: must be string of at least 10 characters"
    
    ok_summary, err_summary = validate_no_raw_log_dump(summary)
    if not ok_summary:
        return False, err_summary
    
    if role == "diagnostician":
        if status == "completed":
            diag = payload.get("diagnosis")
            if not isinstance(diag, dict):
                return False, "Diagnostician completed payload requires 'diagnosis' object"
            for req in ["root_cause_status", "proximate_cause", "evidence", "remediation_plan"]:
                if req not in diag:
                    return False, f"Diagnosis object missing required field: '{req}'"
            if diag["root_cause_status"] not in ("determined", "inconclusive"):
                return False, f"Invalid root_cause_status: {diag['root_cause_status']}"
            if diag["root_cause_status"] == "determined" and not diag.get("root_cause"):
                return False, "Determined diagnosis requires 'root_cause'"
            if diag["root_cause_status"] == "inconclusive" and not diag.get("competing_hypotheses"):
                return False, "Inconclusive diagnosis requires 'competing_hypotheses'"
            if not isinstance(diag.get("evidence"), list) or len(diag["evidence"]) < 1:
                return False, "Diagnosis requires at least one evidence item"
            ok, err = validate_causal_attribution(diag)
            if not ok:
                return False, err
        return True, None

    elif role == "executor":
        if status == "completed":
            if "error_details" in payload:
                return False, "error_details is forbidden when status is 'completed'"
            if "files_modified" not in payload or not isinstance(payload["files_modified"], list):
                return False, "Completed executor payload requires 'files_modified' array"
            test_results = payload.get("test_results")
            if not isinstance(test_results, dict):
                return False, "Completed executor payload requires 'test_results' object"
            if test_results.get("failed", 0) != 0:
                return False, f"Executor cannot complete with failed tests > 0"
        else:
            err = payload.get("error_details")
            if not isinstance(err, dict):
                return False, "Failed executor payload requires 'error_details' object"
            if "failure_kind" not in err or "diagnostic_message" not in err:
                return False, "error_details requires 'failure_kind' and 'diagnostic_message'"
        return True, None

    elif role == "coordinator":
        sub_results = payload.get("subagent_results")
        if not isinstance(sub_results, list) or len(sub_results) < 1:
            return False, "Coordinator payload requires non-empty 'subagent_results' array"
        if status == "completed":
            for child in sub_results:
                if child.get("status") == "failed" and not child.get("advisory", False):
                    return False, "Coordinator cannot report status 'completed' if any non-advisory child failed"
        return True, None

    return False, f"Unknown role: '{role}'"

def validate_payload(role: str, payload: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    try:
        import jsonschema
        from jsonschema import Draft7Validator, FormatChecker
        schema_file = os.path.join(SCHEMAS_DIR, ROLE_SCHEMA_MAP[role])
        if os.path.exists(schema_file):
            with open(schema_file, "r", encoding="utf-8") as f:
                schema = json.load(f)
            validator = Draft7Validator(schema, format_checker=FormatChecker())
            errors = list(validator.iter_errors(payload))
            if not errors:
                summary = payload.get("summary")
                if isinstance(summary, str) and summary:
                    ok_summary, err_summary = validate_no_raw_log_dump(summary)
                    if not ok_summary:
                        return False, err_summary
                if role == "diagnostician" and payload.get("status") == "completed":
                    diag = payload.get("diagnosis")
                    if isinstance(diag, dict):
                        ok, err = validate_causal_attribution(diag)
                        if not ok:
                            return False, err
                return True, None
            first = errors[0]
            path = ".".join(str(p) for p in first.path) if first.path else "root"
            return False, f"Schema validation failed at '{path}': {first.message}"
    except ImportError:
        _jsonschema_available = False
    except Exception as exc:
        return False, f"Schema check error: {exc}"
    
    return validate_payload_builtin(role, payload)

def run_tests() -> bool:
    test_uuid = "123e4567-e89b-12d3-a456-426614174000"
    
    diag_valid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified: database connection leak in worker thread.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager"
        }
    }
    ok, err = validate_payload("diagnostician", diag_valid)
    assert ok, f"Diagnostician valid payload rejected: {err}"
    
    diag_invalid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified but field missing.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "Some proximate cause",
            "evidence": [{"evidence_kind": "source_location", "observation": "obs"}],
            "remediation_plan": "some plan"
        }
    }
    ok, err = validate_payload("diagnostician", diag_invalid)
    assert not ok, "Diagnostician payload missing root_cause should be invalid"

    exec_valid_success = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "All tests executed and passed successfully.",
        "files_modified": ["src/app.py"],
        "test_results": {
            "passed": 5,
            "failed": 0,
            "total": 5,
            "command_executed": "pytest tests/test_app.py"
        }
    }
    ok, err = validate_payload("executor", exec_valid_success)
    assert ok, f"Executor valid success rejected: {err}"

    exec_invalid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Completed with test failures (forbidden).",
        "files_modified": ["src/app.py"],
        "test_results": {
            "passed": 4,
            "failed": 1,
            "total": 5,
            "command_executed": "pytest tests/test_app.py"
        }
    }
    ok, err = validate_payload("executor", exec_invalid)
    assert not ok, "Executor completed with failed > 0 should be invalid"

    exec_valid_fail = {
        "execution_attempt_id": test_uuid,
        "status": "failed",
        "summary": "Unit tests failed on assertion line 42.",
        "error_details": {
            "failure_kind": "SHELL_NON_ZERO_EXIT",
            "diagnostic_message": "pytest exited with code 1"
        }
    }
    ok, err = validate_payload("executor", exec_valid_fail)
    assert ok, f"Executor valid failure rejected: {err}"

    coord_valid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "All subagent tasks completed successfully.",
        "subagent_results": [{
            "task_id": "task-1",
            "worker_role": "executor",
            "status": "completed",
            "summary": "Task 1 completed cleanly"
        }]
    }
    ok, err = validate_payload("coordinator", coord_valid)
    assert ok, f"Coordinator valid payload rejected: {err}"

    coord_invalid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Claimed completed despite child failure.",
        "subagent_results": [{
            "task_id": "task-1",
            "worker_role": "executor",
            "status": "failed",
            "summary": "Task 1 failed"
        }]
    }
    ok, err = validate_payload("coordinator", coord_invalid)
    assert not ok, "Coordinator completed with failed child should be invalid"

    # Summary length boundary tests
    long_summary_valid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "A" * 2000,
        "files_modified": ["src/app.py"],
        "test_results": {"passed": 1, "failed": 0, "total": 1, "command_executed": "pytest"}
    }
    ok, err = validate_payload("executor", long_summary_valid)
    assert ok, f"2000-char summary should be accepted, got error: {err}"

    large_summary_valid = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "A" * 10000,
        "files_modified": ["src/app.py"],
        "test_results": {"passed": 1, "failed": 0, "total": 1, "command_executed": "pytest"}
    }
    ok, err = validate_payload("executor", large_summary_valid)
    assert ok, f"10000-char summary should be accepted, got error: {err}"

    # Causal attribution & Confounding Guard tests
    diag_with_helped = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified with causal attribution.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager",
            "edit_attributions": [
                {
                    "component": "db/pool.py",
                    "change": "Added try/finally connection release block",
                    "observed_divergence": "Connection pool no longer saturates under 10 concurrent requests",
                    "verdict": "helped"
                }
            ],
            "transferable_lesson": {
                "cue": "Whenever managing pooled socket connections",
                "lesson": "Always release connections in guaranteed finally or context exit",
                "evidence": "Observed zero leaked handles during stress test run",
                "confidence": "high"
            }
        }
    }
    ok, err = validate_payload("diagnostician", diag_with_helped)
    assert ok, f"Diagnostician with helped attribution + lesson rejected: {err}"

    diag_with_hurt = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified with hurt attribution.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager",
            "edit_attributions": [
                {
                    "component": "db/pool.py",
                    "change": "Reduced pool size to 1 connection",
                    "observed_divergence": "Deadlock immediately occurred on second request",
                    "verdict": "hurt"
                }
            ],
            "transferable_lesson": {
                "cue": "Whenever sizing thread pools for recursive tasks",
                "lesson": "Never reduce pool capacity below the minimum concurrency threshold",
                "evidence": "Immediate deadlock reproduction when size was clamped",
                "confidence": "high"
            }
        }
    }
    ok, err = validate_payload("diagnostician", diag_with_hurt)
    assert ok, f"Diagnostician with hurt attribution + lesson rejected: {err}"

    diag_confounded = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified with confounded edits.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager",
            "edit_attributions": [
                {
                    "component": "db/pool.py",
                    "change": "Simultaneous refactor of connection pool and lock manager",
                    "observed_divergence": "Test passed but cannot isolate which edit helped",
                    "verdict": "confounded"
                },
                {
                    "component": "db/lock.py",
                    "change": "Changed timeout from 5s to 10s",
                    "observed_divergence": "No measurable difference in run latency",
                    "verdict": "no_observed_effect"
                }
            ],
            "transferable_lesson": {
                "cue": "Whenever touching database pool and locking logic",
                "lesson": "Refactoring both together may improve performance",
                "evidence": "Tests passed after simultaneous modification",
                "confidence": "medium"
            }
        }
    }
    ok, err = validate_payload("diagnostician", diag_confounded)
    assert not ok, "Confounded edit attributions cannot support transferable_lesson and should be rejected"
    assert "Confounded edit attributions cannot support a transferable_lesson" in (err or ""), f"Unexpected error message: {err}"

    diag_empty_attribs = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified with empty edit attributions.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager",
            "edit_attributions": [],
            "transferable_lesson": {
                "cue": "Whenever touching database pool and locking logic",
                "lesson": "Refactoring both together may improve performance",
                "evidence": "Tests passed after simultaneous modification",
                "confidence": "medium"
            }
        }
    }
    ok, err = validate_payload("diagnostician", diag_empty_attribs)
    assert not ok, "Empty edit_attributions with transferable_lesson should be rejected"

    diag_confounded_alone = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Root cause identified with confounded edits but no lesson.",
        "diagnosis": {
            "root_cause_status": "determined",
            "proximate_cause": "OperationalError: connection limit exceeded",
            "root_cause": "Worker pool failed to release connection on timeout",
            "evidence": [{
                "evidence_kind": "source_location",
                "source_file": "db/pool.py",
                "line_number": 42,
                "observation": "Missing connection.close() in finally block"
            }],
            "remediation_plan": "Add connection release in pool context manager",
            "edit_attributions": [
                {
                    "component": "db/pool.py",
                    "change": "Simultaneous refactor of connection pool and lock manager",
                    "observed_divergence": "Test passed but cannot isolate which edit helped",
                    "verdict": "confounded"
                }
            ]
        }
    }
    ok, err = validate_payload("diagnostician", diag_confounded_alone)
    assert ok, f"Confounded attribution without transferable_lesson should be accepted: {err}"

    # REQ-012 Observation Masking / Raw Terminal Dump Guard tests
    payload_ansi = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "Completed task \x1b[31merror found in output\x1b[0m successfully.",
        "files_modified": ["src/app.py"],
        "test_results": {"passed": 1, "failed": 0, "total": 1, "command_executed": "pytest"}
    }
    ok, err = validate_payload("executor", payload_ansi)
    assert not ok, "Payload with ANSI escape in summary must be rejected"
    assert "ANSI escape sequence" in (err or "")

    payload_tb = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": (
            'Diagnosed crash:\n'
            '  File "a.py", line 10, in foo\n'
            '  File "b.py", line 20, in bar\n'
            '  File "c.py", line 30, in baz\n'
            '  File "d.py", line 40, in qux\n'
            'Traceback dumped directly.'
        ),
        "files_modified": ["src/app.py"],
        "test_results": {"passed": 1, "failed": 0, "total": 1, "command_executed": "pytest"}
    }
    ok, err = validate_payload("executor", payload_tb)
    assert not ok, "Payload with >= 4 traceback frames in summary must be rejected"
    assert "traceback frames detected" in (err or "")

    payload_pytest_dump = {
        "execution_attempt_id": test_uuid,
        "status": "completed",
        "summary": "=== test session starts ===\n" + ("x" * 2500),
        "files_modified": ["src/app.py"],
        "test_results": {"passed": 1, "failed": 0, "total": 1, "command_executed": "pytest"}
    }
    ok, err = validate_payload("executor", payload_pytest_dump)
    assert not ok, "Payload with pytest dump > 2000 chars must be rejected"
    assert "=== test session starts ===" in (err or "")

    print("All payload_validator self-tests PASSED.")
    return True

def main():
    parser = argparse.ArgumentParser(description="Validate JSON payload against role schema.")
    parser.add_argument("--role", choices=list(ROLE_SCHEMA_MAP.keys()), help="Target subagent role")
    parser.add_argument("--file", help="Path to JSON file containing payload")
    parser.add_argument("--payload", help="Raw JSON payload string")
    parser.add_argument("--test", action="store_true", help="Run self-tests")
    args = parser.parse_args()

    if args.test:
        success = run_tests()
        sys.exit(0 if success else 1)

    if not args.role:
        parser.error("--role is required when not running --test")

    if args.file:
        with open(args.file, "r", encoding="utf-8") as f:
            data = json.load(f)
    elif args.payload:
        data = json.loads(args.payload)
    else:
        data = json.load(sys.stdin)

    valid, err = validate_payload(args.role, data)
    if valid:
        print("VALID")
        sys.exit(0)
    else:
        print(f"INVALID: {err}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
