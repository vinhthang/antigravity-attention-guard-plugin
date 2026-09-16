import os
import json
import pytest
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from review_gate import (
    validate_review_gate,
    GATE_ERR_MISSING,
    GATE_ERR_EMPTY,
    GATE_ERR_MALFORMED,
    GATE_ERR_MISSING_KEYS,
    GATE_ERR_INVALID_SESSION,
    GATE_ERR_INVALID_ISSUES,
    GATE_ERR_INVALID_SEVERITY,
    GATE_ERR_BLOCKING
)

def test_missing_artifact(tmp_path):
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_MISSING

def test_empty_artifact(tmp_path):
    p = tmp_path / "review.json"
    p.write_text("")
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_EMPTY

def test_malformed_json(tmp_path):
    p = tmp_path / "review.json"
    p.write_text("{not valid json")
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_MALFORMED

def test_missing_required_keys(tmp_path):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({"issues": []}))
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_MISSING_KEYS

def test_invalid_session_id(tmp_path):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({
        "engine": "workbuddy",
        "session_id": "short",
        "issues": []
    }))
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_INVALID_SESSION

def test_invalid_issues_structure(tmp_path):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({
        "engine": "workbuddy",
        "session_id": "workbuddy:valid_session_123",
        "issues": "not a list"
    }))
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_INVALID_ISSUES

def test_invalid_issue_severity(tmp_path):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({
        "engine": "workbuddy",
        "session_id": "workbuddy:valid_session_123",
        "issues": [{"severity": "P99", "description": "Invalid severity"}]
    }))
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_INVALID_SEVERITY

def test_blocking_issues(tmp_path):
    p = tmp_path / "review.json"
    p.write_text(json.dumps({
        "engine": "workbuddy",
        "session_id": "workbuddy:valid_session_123",
        "issues": [{"severity": "P0", "description": "Critical blocker"}]
    }))
    ok, err = validate_review_gate(str(tmp_path))
    assert not ok
    assert err == GATE_ERR_BLOCKING

def test_clean_review_pass(tmp_path):
    p = tmp_path / "custom_review.json"
    p.write_text(json.dumps({
        "engine": "workbuddy",
        "session_id": "workbuddy:valid_session_123",
        "issues": [{"severity": "P2", "description": "Advisory note"}]
    }))
    ok, err = validate_review_gate(str(tmp_path), artifact_path=str(p))
    assert ok
    assert err is None
