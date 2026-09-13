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
    if not isinstance(summary, str) or len(summary) < 10 or len(summary) > 1200:
        return False, f"Invalid summary: must be string between 10 and 1200 characters"
    
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
