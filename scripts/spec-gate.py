#!/usr/bin/env python3
"""Mechanical Pre-Tool Spec Gate Hook (REQ-031).

Intercepts invoke_subagent calls to prevent unauthorized code mutations
when no active, validated specification package exists in docs/specs/.
"""

import importlib.util
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, Optional

EXEMPT_ROLES = {"research", "codebase researcher", "diagnostician"}
EXEMPT_TYPES = {"research", "translate", "evaluate", "refine", "analyze"}
TRANSLATION_TYPES = {"translate", "evaluate", "refine", "analyze"}

MUTATION_KEYWORDS = {
    "implement",
    "modify",
    "code",
    "compiler",
    "executor",
    "builder",
    "patch",
    "write_to_file",
    "replace_file_content",
}


def load_spec_checker():
    """Dynamically load spec_checker module from ai-review-plugin or sys.path."""
    try:
        import spec_checker
        return spec_checker
    except ImportError as exc:
        _ = str(exc)

    candidates = [
        Path(__file__).resolve().parent.parent.parent / "ai-review-plugin" / "scripts" / "spec_checker.py",
        Path.home() / ".gemini" / "config" / "plugins" / "ai-review-plugin" / "scripts" / "spec_checker.py",
        Path("/Users/thanghoang/github/ai-review-plugin/scripts/spec_checker.py"),
    ]
    for cand in candidates:
        if cand.exists():
            spec = importlib.util.spec_from_file_location("spec_checker", str(cand))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                sys.modules["spec_checker"] = mod
                spec.loader.exec_module(mod)
                return mod
    return None


def is_exempt_subagent(sa: Dict[str, Any]) -> bool:
    """Check if subagent qualifies for exemption from spec gate."""
    type_name = str(sa.get("TypeName") or "").strip().lower()
    role = str(sa.get("Role") or "").strip().lower()
    prompt = str(sa.get("Prompt") or "").strip().lower()

    # Read-only research exemption
    if type_name == "research" or role in EXEMPT_ROLES:
        return True

    # Translation pipeline operating on runs/
    if type_name in TRANSLATION_TYPES:
        if "runs/" in prompt or "runs\\" in prompt or role in TRANSLATION_TYPES:
            return True

    return False


def is_mutating_subagent(sa: Dict[str, Any]) -> bool:
    """Check if subagent role or prompt indicates code mutation."""
    type_name = str(sa.get("TypeName") or "").strip().lower()
    role = str(sa.get("Role") or "").strip().lower()
    prompt = str(sa.get("Prompt") or "").strip().lower()

    if type_name == "self":
        return True

    for kw in MUTATION_KEYWORDS:
        if kw in role or kw in prompt:
            return True

    return False


def evaluate_spec_gate(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate spec-gate decision for given PreToolUse payload."""
    tool_call = payload.get("toolCall", {})
    tool_name = tool_call.get("name", "")

    if tool_name not in ["invoke_subagent", "default_api:invoke_subagent"]:
        return {"decision": "allow"}

    args = tool_call.get("args", {})
    subagents = args.get("Subagents", [])
    if not subagents or not isinstance(subagents, list):
        return {"decision": "allow"}

    # Check subagents
    requires_gate = False
    for sa in subagents:
        if is_exempt_subagent(sa):
            continue
        if is_mutating_subagent(sa):
            requires_gate = True
            break
        # Default fail-closed for non-exempt subagents
        requires_gate = True
        break

    if not requires_gate:
        return {"decision": "allow"}

    # Resolve workspace root
    workspace_root = payload.get("cwd") or os.environ.get("AGY_ACTIVE_WORKSPACE") or os.getcwd()

    checker = load_spec_checker()
    if checker:
        result = checker.verify_active_specification(workspace_root)
    else:
        # Fallback inspection if module not importable
        specs_dir = Path(workspace_root) / "docs" / "specs"
        if not specs_dir.exists():
            result = {"status": "no_spec_framework", "valid": True}
        elif not (specs_dir / "INDEX.md").exists():
            result = {"status": "invalid", "valid": False, "reason": "Missing docs/specs/INDEX.md"}
        else:
            result = {"status": "no_active_spec", "valid": False, "reason": "No active specification found in docs/specs/INDEX.md"}

    if not result.get("valid"):
        reason_detail = result.get("reason", "No active specification found.")
        return {
            "decision": "deny",
            "reason": (
                f"Spec Gate Rejection: Cannot dispatch execution subagent.\n"
                f"{reason_detail}\n"
                f"Scaffold docs/specs/<feature-id>/, register in INDEX.md, and secure explicit approval ('Proceed') before code implementation."
            ),
        }

    return {"decision": "allow"}


def main(argv=None, stdin=None, stdout=None):
    if argv is None:
        argv = sys.argv
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    def emit(data):
        if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
            stdout.write(json.dumps({"decision": "allow"}) + "\n")
        else:
            stdout.write(json.dumps(data) + "\n")

    try:
        raw = stdin.read()
        if not raw or not raw.strip():
            emit({"decision": "allow"})
            return

        payload = json.loads(raw)
        decision = evaluate_spec_gate(payload)
        emit(decision)
    except Exception as exc:
        emit({"decision": "deny", "reason": f"Spec Gate Exception: {exc}"})


if __name__ == "__main__":
    main()
