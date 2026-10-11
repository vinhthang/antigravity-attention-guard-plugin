#!/usr/bin/env python3
"""Unit tests for PreToolUse Spec Gate Hook (REQ-031)."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

spec = importlib.util.spec_from_file_location(
    "spec_gate",
    SCRIPTS_DIR / "spec-gate.py"
)
spec_gate_mod = importlib.util.module_from_spec(spec)
sys.modules["spec_gate"] = spec_gate_mod
spec.loader.exec_module(spec_gate_mod)

evaluate_spec_gate = spec_gate_mod.evaluate_spec_gate
is_exempt_subagent = spec_gate_mod.is_exempt_subagent
is_mutating_subagent = spec_gate_mod.is_mutating_subagent


class TestSpecGate(unittest.TestCase):
    """Test suite for spec-gate.py."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.workspace = Path(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_exempt_research_subagent(self):
        """Research subagents are exempt from spec gate."""
        payload = {
            "cwd": str(self.workspace),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "research",
                            "Role": "Codebase Researcher",
                            "Prompt": "Search codebase for references to spec gate",
                        }
                    ]
                },
            },
        }
        decision = evaluate_spec_gate(payload)
        self.assertEqual(decision.get("decision"), "allow")

    def test_exempt_translation_pipeline(self):
        """Translation subagents working on runs/ are exempt."""
        payload = {
            "cwd": str(self.workspace),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "translate",
                            "Role": "Translator",
                            "Prompt": "Translate runs/sample_book/ch01/source.txt to vietnamese",
                        }
                    ]
                },
            },
        }
        decision = evaluate_spec_gate(payload)
        self.assertEqual(decision.get("decision"), "allow")

    def test_denial_mutating_subagent_no_active_spec(self):
        """Mutating subagent is denied when no active spec exists."""
        specs_dir = self.workspace / "docs" / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "INDEX.md").write_text(
            "| Feature ID | Title | Status | REQ Range | Key Decisions | Spec Path |\n"
            "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            "| `feat-old` | Old Feature | Completed | `REQ-001` | ADR | `./feat-old/spec.md` |\n",
            encoding="utf-8",
        )

        payload = {
            "cwd": str(self.workspace),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "self",
                            "Role": "Feature Implementer",
                            "Prompt": "Implement feature by modifying scripts/helper.py",
                        }
                    ]
                },
            },
        }
        decision = evaluate_spec_gate(payload)
        self.assertEqual(decision.get("decision"), "deny")
        self.assertIn("Spec Gate Rejection", decision.get("reason", ""))
        self.assertIn("No active specification found", decision.get("reason", ""))

    def test_allowance_mutating_subagent_with_valid_active_spec(self):
        """Mutating subagent is allowed when a valid active spec package exists."""
        repo_root = Path(__file__).resolve().parent.parent.parent / "ai-review-plugin"
        payload = {
            "cwd": str(repo_root),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "self",
                            "Role": "Feature Implementer",
                            "Prompt": "Implement spec-gate feature in code",
                        }
                    ]
                },
            },
        }
        decision = evaluate_spec_gate(payload)
        self.assertEqual(decision.get("decision"), "allow")

    def test_non_subagent_tool_allowed(self):
        """Non-subagent tool calls are unconditionally allowed by spec-gate."""
        payload = {
            "cwd": str(self.workspace),
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "ls -la"},
            },
        }
        decision = evaluate_spec_gate(payload)
        self.assertEqual(decision.get("decision"), "allow")

    def test_cli_execution_via_stdin(self):
        """Test executing spec-gate.py CLI via stdin."""
        script_path = SCRIPTS_DIR / "spec-gate.py"
        repo_root = Path(__file__).resolve().parent.parent.parent / "ai-review-plugin"

        # Allowed request
        payload_allow = {
            "cwd": str(repo_root),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"TypeName": "research", "Role": "Researcher", "Prompt": "Find files"}
                    ]
                },
            },
        }
        proc = subprocess.run(
            [sys.executable, str(script_path)],
            input=json.dumps(payload_allow),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0)
        data = json.loads(proc.stdout)
        self.assertEqual(data.get("decision"), "allow")

        # Denied request (no active spec in empty temp workspace)
        specs_dir = self.workspace / "docs" / "specs"
        specs_dir.mkdir(parents=True)
        (specs_dir / "INDEX.md").write_text(
            "| Feature ID | Title | Status | REQ Range | Key Decisions | Spec Path |\n"
            "| :--- | :--- | :--- | :--- | :--- | :--- |\n"
            "| `feat-old` | Old Feature | Completed | `REQ-001` | ADR | `./feat-old/spec.md` |\n",
            encoding="utf-8",
        )
        payload_deny = {
            "cwd": str(self.workspace),
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"TypeName": "self", "Role": "Coder", "Prompt": "Write to file scripts/test.py"}
                    ]
                },
            },
        }
        proc_deny = subprocess.run(
            [sys.executable, str(script_path)],
            input=json.dumps(payload_deny),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc_deny.returncode, 0)
        data_deny = json.loads(proc_deny.stdout)
        self.assertEqual(data_deny.get("decision"), "deny")
        self.assertIn("Spec Gate Rejection", data_deny.get("reason", ""))


if __name__ == "__main__":
    unittest.main()
