#!/usr/bin/env python3
"""Cross-Plugin End-to-End Hook Pipeline & Ecosystem Audit Integration Tests (REQ-014, REQ-015).

Tests the complete Antigravity 2.0 Primary Agent + Subagent lifecycle across:
- PreInvocation: attention-refresh.py
- PreToolUse: spec-gate.py, enforce-delegation.py, inject-rules.py
- PostToolUse: record-tool-result.py
- Stop: attention-check.py (with NO_TOOL_CALL, subagent token transitions, and Walkthrough Gate)
- Ecosystem Audit CLI: system_audit.py
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import pytest

# Ensure scripts dir is on sys.path
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import common
from fsm import FSM, Event, State
from ledger import Ledger


def _load_script_module(name: str, filename: str):
    script_path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, str(script_path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module from {script_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


enforce_mod = _load_script_module("enforce_delegation_e2e", "enforce-delegation.py")
inject_mod = _load_script_module("inject_rules_e2e", "inject-rules.py")
record_mod = _load_script_module("record_tool_result_e2e", "record-tool-result.py")
attention_check_mod = _load_script_module("attention_check_e2e", "attention-check.py")
system_audit_mod = _load_script_module("system_audit_e2e", "system_audit.py")

# Also load spec-gate.py
SPEC_GATE_PATH = Path("/Users/thanghoang/.gemini/config/plugins/spec-driven-plugin/scripts/spec-gate.py")
if not SPEC_GATE_PATH.is_file():
    SPEC_GATE_PATH = SCRIPTS_DIR / "spec-gate.py"

spec_gate_spec = importlib.util.spec_from_file_location("spec_gate_e2e", str(SPEC_GATE_PATH))
if spec_gate_spec and spec_gate_spec.loader:
    spec_gate_mod = importlib.util.module_from_spec(spec_gate_spec)
    sys.modules["spec_gate_e2e"] = spec_gate_mod
    spec_gate_spec.loader.exec_module(spec_gate_mod)
else:
    spec_gate_mod = None


def run_hook(mod: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    mod.main(argv=["test"], stdin=stdin, stdout=stdout)
    out_str = stdout.getvalue().strip()
    return json.loads(out_str) if out_str else {}


@pytest.fixture
def e2e_env(tmp_path, monkeypatch):
    """Set up an isolated test environment with temporary AGY_APP_DATA_DIR and workspace."""
    app_data_dir = tmp_path / "app_data"
    app_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data_dir))

    ws_dir = tmp_path / "workspace"
    ws_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGY_ACTIVE_WORKSPACE", str(ws_dir))

    # Scaffold valid docs/specs/INDEX.md and approved spec package
    specs_dir = ws_dir / "docs" / "specs" / "test-feature"
    specs_dir.mkdir(parents=True, exist_ok=True)

    index_file = ws_dir / "docs" / "specs" / "INDEX.md"
    index_file.write_text(
        "# Specification Catalog\n\n"
        "| Feature ID | Title | Status | Requirement Range | Key Decisions | Spec Path |\n"
        "|---|---|---|---|---|---|\n"
        "| test-feature | Test Feature | In-Progress | REQ-001 | ADR-001 | [spec.md](test-feature/spec.md) |\n",
        encoding="utf-8",
    )

    (specs_dir / "spec.md").write_text("# Spec\n\n### `REQ-001` — Feature Spec\n- Acceptance criteria.\n", encoding="utf-8")
    (specs_dir / "design.md").write_text("# Design\nREQ-001 architectural design.\n", encoding="utf-8")
    (specs_dir / "tasks.md").write_text("# Tasks\n- [ ] Task 1 covering REQ-001\n", encoding="utf-8")
    (specs_dir / "decisions.md").write_text("# Decisions\n## ADR-001: Decision covering REQ-001\n", encoding="utf-8")

    ledger_db = app_data_dir / "attention_guard.db"
    ledger = Ledger(db_path=str(ledger_db))

    return {
        "app_data_dir": app_data_dir,
        "ws_dir": ws_dir,
        "ledger": ledger,
        "ledger_db": ledger_db,
    }


# ============================================================================
# Test 1: Full Primary + Subagent Lifecycle with NO_TOOL_CALL (REQ-014, REQ-015)
# ============================================================================

def test_full_primary_and_subagent_lifecycle_with_no_tool_call(e2e_env):
    """Verify the entire multi-hook lifecycle using Antigravity 2.0 payloads:

    (a) spec-gate.py + enforce-delegation.py + inject-rules.py on flat invoke_subagent.
    (b) record-tool-result.py on PostToolUse(invoke_subagent) -> EXECUTION_ACTIVE & ACTIVE work_item.
    (c) Subagent step_index=0 token claim + edit_file + run_command -> WORK_CLAIMED & RUNNING.
    (d) attention-check.py on subagent Stop with terminationReason='NO_TOOL_CALL' -> COMPLETED & WORK_TERMINATED_OK.
    (e) attention-check.py on Primary Agent Stop BEFORE walkthrough.md -> Walkthrough Gate decision='continue'.
    (f) Create fresh walkthrough.md -> attention-check.py returns decision='allow' -> CLOSED.
    """
    app_data_dir = e2e_env["app_data_dir"]
    ws_dir = e2e_env["ws_dir"]
    ledger = e2e_env["ledger"]

    primary_conv_id = f"primary-{uuid.uuid4().hex[:8]}"
    primary_transcript = app_data_dir / "brain" / primary_conv_id / "transcript.jsonl"
    primary_transcript.parent.mkdir(parents=True, exist_ok=True)
    primary_transcript.write_text(
        json.dumps({"step_index": 0, "source": "USER", "type": "USER_INPUT", "content": "Implement feature"}) + "\n",
        encoding="utf-8",
    )

    # ------------------------------------------------------------------------
    # (a) PreToolUse on flat invoke_subagent
    # ------------------------------------------------------------------------
    invoke_args = {
        "TypeName": "self",
        "Role": "Executor",
        "Prompt": "Implement feature code in src/app.py",
    }
    primary_payload = {
        "tool_name": "invoke_subagent",
        "tool_call": {"name": "invoke_subagent", "args": invoke_args},
        "toolCall": {"name": "invoke_subagent", "args": invoke_args},
        "modelName": "claude-opus-4.6",
        "cwd": str(ws_dir),
        "workspacePaths": [str(ws_dir)],
        "conversationId": primary_conv_id,
        "transcriptPath": str(primary_transcript),
        "stepIdx": 0,
    }

    # 1. spec-gate.py
    if spec_gate_mod is not None:
        sg_res = run_hook(spec_gate_mod, primary_payload)
        assert sg_res.get("decision") == "allow", f"spec-gate rejected: {sg_res}"

    # 2. enforce-delegation.py
    enf_res = run_hook(enforce_mod, primary_payload)
    assert enf_res.get("decision") == "allow", f"enforce-delegation rejected: {enf_res}"

    # 3. inject-rules.py
    inj_res = run_hook(inject_mod, primary_payload)
    assert inj_res.get("decision") == "allow", f"inject-rules rejected: {inj_res}"
    assert "overwrite" in inj_res, "inject-rules must provide overwrite dictionary"
    overwrite = inj_res["overwrite"]
    assert overwrite.get("Model") == "flash", "Primary thinking model must coerce child subagent to flash"

    injected_prompt = overwrite.get("Prompt", "")
    assert "[ANTIGRAVITY_TOKEN:" in injected_prompt, "Token marker must be injected into prompt"
    token_match = re.search(r"\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]", injected_prompt)
    assert token_match is not None, "Failed to extract UUID token from injected prompt"
    token = token_match.group(1)

    # ------------------------------------------------------------------------
    # (b) record-tool-result.py on PostToolUse(invoke_subagent)
    # ------------------------------------------------------------------------
    post_payload = {
        "conversationId": primary_conv_id,
        "transcriptPath": str(primary_transcript),
        "stepIdx": 0,
        "toolCall": {"name": "invoke_subagent", "args": overwrite},
        "toolResult": {"status": "dispatched", "conversationId": f"sub-{token[:8]}"},
    }
    rec_res = run_hook(record_mod, post_payload)
    assert rec_res == {} or rec_res.get("decision") in (None, "allow")

    # Verify FSM is EXECUTION_ACTIVE
    fsm = FSM()
    with ledger._get_connection() as conn:
        rows = conn.execute(
            "SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at ASC",
            (f"{primary_conv_id}_0_%",),
        ).fetchall()
        for r in rows:
            try:
                fsm.transition(Event[r[0]], json.loads(r[1]) if r[1] else {})
            except KeyError as exc:
                _ = exc
        assert fsm.state == State.EXECUTION_ACTIVE, f"Expected EXECUTION_ACTIVE, got {fsm.state}"

        # Verify work_item is ACTIVE
        item = conn.execute("SELECT status FROM work_items WHERE work_id = ?", (token,)).fetchone()
        assert item is not None and item[0] == "ACTIVE", f"Expected ACTIVE work_item, got {item}"

    # ------------------------------------------------------------------------
    # (c) Subagent Execution with token claim, edit_file, and run_command
    # ------------------------------------------------------------------------
    subagent_conv_id = f"subagent-{token[:8]}"
    subagent_transcript = app_data_dir / "brain" / subagent_conv_id / "transcript.jsonl"
    subagent_transcript.parent.mkdir(parents=True, exist_ok=True)
    subagent_transcript.write_text(
        json.dumps({
            "step_index": 0,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "content": f"<SYSTEM_MESSAGE>[ANTIGRAVITY_TOKEN:{token}]\nYou are a subagent.</SYSTEM_MESSAGE>",
        }) + "\n",
        encoding="utf-8",
    )

    # Subagent executes edit_file (Antigravity 2.0 schema)
    sub_edit_payload = {
        "tool_name": "edit_file",
        "toolCall": {
            "name": "edit_file",
            "args": {"Path": "src/app.py", "Target": "pass", "Replacement": "return True"},
        },
        "conversationId": subagent_conv_id,
        "transcriptPath": str(subagent_transcript),
    }
    sub_edit_res = run_hook(enforce_mod, sub_edit_payload)
    assert sub_edit_res.get("decision") == "allow", f"Subagent edit_file was rejected: {sub_edit_res}"

    # Subagent executes run_command
    sub_cmd_payload = {
        "tool_name": "run_command",
        "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk pytest tests/ -v"}},
        "conversationId": subagent_conv_id,
        "transcriptPath": str(subagent_transcript),
    }
    sub_cmd_res = run_hook(enforce_mod, sub_cmd_payload)
    assert sub_cmd_res.get("decision") == "allow", f"Subagent run_command was rejected: {sub_cmd_res}"

    # Verify token claimed and RUNNING in ledger
    with ledger._get_connection() as conn:
        tok_row = conn.execute("SELECT claimed, claimed_by FROM tokens WHERE token_id = ?", (token,)).fetchone()
        assert tok_row is not None and tok_row[0] == 1, "Token must be marked claimed"
        assert tok_row[1] == subagent_conv_id, f"Token claimed_by must match {subagent_conv_id}"

        sub_events = [
            r[0]
            for r in conn.execute(
                "SELECT type FROM events WHERE event_id LIKE ? ORDER BY created_at ASC",
                (f"{subagent_conv_id}_%",),
            ).fetchall()
        ]
        assert "WORK_CLAIMED" in sub_events, "WORK_CLAIMED event must be recorded"
        assert "RUNNING" in sub_events, "RUNNING event must be recorded"

    # ------------------------------------------------------------------------
    # (d) Run attention-check.py on subagent Stop with NO_TOOL_CALL
    # ------------------------------------------------------------------------
    sub_stop_payload = {
        "conversationId": subagent_conv_id,
        "transcriptPath": str(subagent_transcript),
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "error": "",
    }
    sub_stop_res = run_hook(attention_check_mod, sub_stop_payload)
    assert sub_stop_res.get("decision") == "allow"

    # Verify work_item status transitioned to COMPLETED
    with ledger._get_connection() as conn:
        item_row = conn.execute("SELECT status FROM work_items WHERE work_id = ?", (token,)).fetchone()
        assert item_row is not None and item_row[0] == "COMPLETED", f"Expected COMPLETED, got {item_row}"

        term_events = conn.execute("SELECT type FROM events WHERE type = 'WORK_TERMINATED_OK'").fetchall()
        assert len(term_events) >= 1, "WORK_TERMINATED_OK event must be recorded in Ledger"

    # ------------------------------------------------------------------------
    # (e) Run attention-check.py on Primary Agent Stop BEFORE walkthrough.md
    # ------------------------------------------------------------------------
    primary_stop_payload = {
        "conversationId": primary_conv_id,
        "transcriptPath": str(primary_transcript),
        "terminationReason": "NO_TOOL_CALL",
        "fullyIdle": True,
        "modelName": "claude-opus-4.6",
    }
    pri_stop_res = run_hook(attention_check_mod, primary_stop_payload)
    assert pri_stop_res.get("decision") == "continue", (
        f"Walkthrough Gate must fire and return decision='continue' when walkthrough.md is missing. Got: {pri_stop_res}"
    )
    assert "Walkthrough Gate" in pri_stop_res.get("reason", "")

    # ------------------------------------------------------------------------
    # (f) Create fresh walkthrough.md and re-run Primary Agent Stop
    # ------------------------------------------------------------------------
    brain_dir = app_data_dir / "brain" / primary_conv_id
    brain_dir.mkdir(parents=True, exist_ok=True)
    wt_file = brain_dir / "walkthrough.md"
    wt_file.write_text("# Walkthrough\nFeature implementation verified.\n", encoding="utf-8")

    pri_stop_res2 = run_hook(attention_check_mod, primary_stop_payload)
    assert pri_stop_res2.get("decision") == "allow", f"Primary stop with fresh walkthrough rejected: {pri_stop_res2}"

    # Verify FSM transitions to CLOSED
    fsm_final = FSM()
    with ledger._get_connection() as conn:
        rows = conn.execute(
            "SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at ASC",
            (f"{primary_conv_id}_0_%",),
        ).fetchall()
        for r in rows:
            try:
                fsm_final.transition(Event[r[0]], json.loads(r[1]) if r[1] else {})
            except KeyError as exc:
                _ = exc
        assert fsm_final.state == State.CLOSED, f"Expected CLOSED state, got {fsm_final.state}"


# ============================================================================
# Test 2: Step 0 sender=<uuid> Subagent Fallback (REQ-014)
# ============================================================================

def test_step0_sender_subagent_fallback(tmp_path, monkeypatch):
    """Verify common.is_subagent recognizes subagents via step_index=0 sender=<parent_uuid> fallback."""
    tpath = tmp_path / "transcript_sender.jsonl"
    parent_uuid = str(uuid.uuid4())
    child_conv_id = f"child-{uuid.uuid4().hex[:8]}"

    # 1. Valid sender fallback step 0
    tpath.write_text(
        json.dumps({
            "step_index": 0,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "content": f"[Message] timestamp=2026-10-21T03:59:37Z sender={parent_uuid} priority=HIGH content={{}}",
        }) + "\n",
        encoding="utf-8",
    )

    data = {"transcriptPath": str(tpath), "conversationId": child_conv_id}
    is_sub, is_ver, depth, p_conv, p_turn = common.is_subagent(data)
    assert is_sub is True, "Must identify as subagent via step 0 sender fallback"
    assert is_ver is False, "Fallback subagents are unverified (no cryptographic token claimed)"
    assert depth == 0
    assert p_conv == parent_uuid
    assert p_turn == "0"

    # 2. Self-message (sender == conv_id) must NOT be identified as subagent
    data_self = {"transcriptPath": str(tpath), "conversationId": parent_uuid}
    is_sub_self, _, _, _, _ = common.is_subagent(data_self)
    assert is_sub_self is False, "Self-message sender == conv_id must not identify as subagent"

    # 3. Fallback disabled via AGY_DISABLE_SENDER_FALLBACK=1
    monkeypatch.setenv("AGY_DISABLE_SENDER_FALLBACK", "1")
    is_sub_dis, _, _, _, _ = common.is_subagent(data)
    assert is_sub_dis is False, "Sender fallback must be disabled when AGY_DISABLE_SENDER_FALLBACK=1"


# ============================================================================
# Test 3: Subagent Doom-Loop & Test-Tampering E2E (REQ-008, REQ-009)
# ============================================================================

def test_subagent_doom_loop_and_test_tampering_e2e(tmp_path, monkeypatch):
    """Verify test-tampering detection and subagent doom-loop circuit breaker:

    - edit_file introducing skip marker to tests/test_x.py is denied.
    - 3 consecutive identical run_command executions trigger doom-loop circuit breaker.
    - Intervening edit_file resets the counter and allows subsequent run_command.
    """
    app_data_dir = tmp_path / "app_data"
    app_data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data_dir))

    ledger_db = app_data_dir / "attention_guard.db"
    ledger = Ledger(db_path=str(ledger_db))

    token = str(uuid.uuid4())
    subagent_conv_id = f"subagent-doom-{uuid.uuid4().hex[:8]}"

    # Setup ledger with WORK_PREPARED
    ledger.insert_event(
        "parent", "0", "PreToolUse", "0", token, "WORK_PREPARED",
        json.dumps({
            "token": token,
            "may_delegate": False,
            "remaining_depth": 0,
            "parent_conv_id": "parent",
            "parent_turn_id": "0",
        }),
    )
    with ledger._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id, claimed, claimed_by) VALUES (?, 0, NULL)", (token,))
        conn.execute(
            "INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id) VALUES (?, 'ACTIVE', 1.0, 1.0, 'parent', '0')",
            (token,),
        )

    tpath = app_data_dir / "brain" / subagent_conv_id / "transcript.jsonl"
    tpath.parent.mkdir(parents=True, exist_ok=True)
    tpath.write_text(
        json.dumps({
            "step_index": 0,
            "source": "SYSTEM",
            "type": "SYSTEM_MESSAGE",
            "content": f"<SYSTEM_MESSAGE>[ANTIGRAVITY_TOKEN:{token}]\nYou are a subagent.</SYSTEM_MESSAGE>",
        }) + "\n",
        encoding="utf-8",
    )

    # 1. Test tampering check on test file (concatenate marker to avoid self-triggering static guard)
    skip_marker = "pytest." + "skip('bypassing test')"
    tamper_payload = {
        "tool_name": "edit_file",
        "toolCall": {
            "name": "edit_file",
            "args": {
                "Path": "tests/test_calculator.py",
                "Target": "def test_add():",
                "Replacement": f"def test_add():\n    {skip_marker}",
            },
        },
        "conversationId": subagent_conv_id,
        "transcriptPath": str(tpath),
    }
    tamper_res = run_hook(enforce_mod, tamper_payload)
    assert tamper_res.get("decision") == "deny"
    assert "Test tampering detected" in tamper_res.get("reason", "")

    # 2. 3 consecutive identical run_command executions
    cmd_payload = {
        "tool_name": "run_command",
        "toolCall": {"name": "run_command", "args": {"CommandLine": "rtk pytest tests/ -v"}},
        "conversationId": subagent_conv_id,
        "transcriptPath": str(tpath),
    }

    # Run 1: allow
    res1 = run_hook(enforce_mod, cmd_payload)
    assert res1.get("decision") == "allow", f"Run 1 rejected: {res1}"

    # Run 2: allow
    res2 = run_hook(enforce_mod, cmd_payload)
    assert res2.get("decision") == "allow", f"Run 2 rejected: {res2}"

    # Run 3: must be DENIED by doom-loop circuit breaker
    res3 = run_hook(enforce_mod, cmd_payload)
    assert res3.get("decision") == "deny", f"Run 3 should have been denied, got: {res3}"
    assert "Subagent doom-loop circuit breaker" in res3.get("reason", "")

    # 3. Intervening edit_file resets circuit breaker counter
    intervening_edit = {
        "tool_name": "edit_file",
        "toolCall": {
            "name": "edit_file",
            "args": {"Path": "src/fix.py", "Target": "x = 1", "Replacement": "x = 2"},
        },
        "conversationId": subagent_conv_id,
        "transcriptPath": str(tpath),
    }
    res_edit = run_hook(enforce_mod, intervening_edit)
    assert res_edit.get("decision") == "allow", f"Intervening edit rejected: {res_edit}"

    # 4. Next run_command is permitted after the reset
    res4 = run_hook(enforce_mod, cmd_payload)
    assert res4.get("decision") == "allow", f"Run after file edit reset rejected: {res4}"


# ============================================================================
# Test 4: Ecosystem Audit CLI & SQLite Ledger Repair (REQ-015)
# ============================================================================

def test_ecosystem_audit_cli_and_ledger_repair(tmp_path, monkeypatch):
    """Verify system_audit.py audits hooks, agents, plugin surface, and ledger repair."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    plugins_dir = tmp_path / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    # 1. Author valid hooks.json in config_dir
    script_dummy = config_dir / "dummy_gate.py"
    script_dummy.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    script_dummy.chmod(0o755)

    hooks_json = config_dir / "hooks.json"
    hooks_json.write_text(
        json.dumps({
            "test-gate": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [{"type": "command", "command": f"/usr/bin/env python3 {script_dummy}"}],
                    }
                ]
            }
        }),
        encoding="utf-8",
    )

    # Test audit_hooks_config
    h_ok, h_errs, h_info = system_audit_mod.audit_hooks_config(hooks_json)
    assert h_ok is True
    assert len(h_errs) == 0
    assert str(script_dummy) in h_info["scripts_verified"]

    # 2. Author a dummy plugin with valid agents and surface
    dummy_plugin = plugins_dir / "test-plugin"
    dummy_plugin.mkdir(parents=True, exist_ok=True)
    (dummy_plugin / "plugin.json").write_text(json.dumps({"name": "test-plugin"}), encoding="utf-8")

    agents_dir = dummy_plugin / "agents"
    agents_dir.mkdir(parents=True, exist_ok=True)
    (agents_dir / "valid-agent.md").write_text(
        "---\n"
        "name: valid-agent\n"
        "description: Valid agent definition\n"
        "tools: [read_file, view_file, write_file, write_to_file]\n"
        "---\n\n# Valid Agent\n",
        encoding="utf-8",
    )
    a_ok, a_errs = system_audit_mod.audit_agents_dir(dummy_plugin)
    assert a_ok is True
    assert len(a_errs) == 0

    # Test agents audit with missing write_file
    (agents_dir / "legacy-agent.md").write_text(
        "---\n"
        "name: legacy-agent\n"
        "description: Legacy agent without write_file\n"
        "tools: [write_to_file]\n"
        "---\n\n# Legacy Agent\n",
        encoding="utf-8",
    )
    a_ok2, a_errs2 = system_audit_mod.audit_agents_dir(dummy_plugin)
    assert a_ok2 is False
    assert any("declares legacy 'write_to_file' but lacks Antigravity 2.0 'write_file'" in e for e in a_errs2)
    (agents_dir / "legacy-agent.md").unlink()  # remove to restore valid state

    # 3. Test SQLite Ledger audit and repair
    db_file = tmp_path / "audit_test.db"
    ledger = Ledger(db_path=str(db_file))
    now = time.time()

    with ledger._get_connection() as conn:
        # Fresh active item
        conn.execute(
            "INSERT INTO work_items (work_id, status, created_at, updated_at) VALUES ('active-fresh', 'ACTIVE', ?, ?)",
            (now, now),
        )
        # Stale active item (> 3600s old)
        conn.execute(
            "INSERT INTO work_items (work_id, status, created_at, updated_at) VALUES ('active-stale', 'ACTIVE', ?, ?)",
            (now - 4000, now - 4000),
        )
        # Recent timed_out item
        conn.execute(
            "INSERT INTO work_items (work_id, status, created_at, updated_at) VALUES ('to-recent', 'TIMED_OUT', ?, ?)",
            (now - 1000, now - 1000),
        )
        # Old timed_out item (> 86400s old)
        conn.execute(
            "INSERT INTO work_items (work_id, status, created_at, updated_at) VALUES ('to-old', 'TIMED_OUT', ?, ?)",
            (now - 90000, now - 90000),
        )
        conn.execute("INSERT INTO events (event_id, type, payload, created_at) VALUES ('ev-1', 'TEST', '{}', ?)", (now,))

    # Audit without repair
    l_ok, l_errs, l_stats = system_audit_mod.audit_sqlite_ledger(db_file, repair=False)
    assert l_ok is True
    assert l_stats["work_items"]["active"] == 2
    assert l_stats["work_items"]["timed_out"] == 2

    # Audit with repair=True
    l_ok_rep, l_errs_rep, l_stats_rep = system_audit_mod.audit_sqlite_ledger(db_file, repair=True)
    assert l_ok_rep is True
    rep_info = l_stats_rep.get("repair", {})
    assert rep_info.get("active_marked_terminated") == 1, "Must mark 1 stale active as terminated"
    assert rep_info.get("stale_timed_out_deleted") == 1, "Must delete 1 old timed_out row"

    with ledger._get_connection() as conn:
        stale_item = conn.execute("SELECT status FROM work_items WHERE work_id = 'active-stale'").fetchone()
        assert stale_item[0] == "TERMINATED", "Stale item must be transitioned to TERMINATED"
        old_to_item = conn.execute("SELECT 1 FROM work_items WHERE work_id = 'to-old'").fetchone()
        assert old_to_item is None, "Old TIMED_OUT row must be deleted"

    # 4. Test audit_ecosystem function and main CLI
    eco_report = system_audit_mod.audit_ecosystem(
        plugins_root=plugins_dir,
        config_root=config_dir,
        db_path=db_file,
        repair_db=False,
    )
    assert eco_report["valid"] is True
    assert "test-plugin" in eco_report["plugins"]
    assert eco_report["ledger"]["valid"] is True

    # Test CLI main with --json
    cli_out = io.StringIO()
    monkeypatch.setattr(sys, "stdout", cli_out)
    exit_code = system_audit_mod.main([
        "--plugins-root", str(plugins_dir),
        "--config-root", str(config_dir),
        "--db-path", str(db_file),
        "--json",
    ])
    assert exit_code == 0
    cli_json = json.loads(cli_out.getvalue())
    assert cli_json["valid"] is True
