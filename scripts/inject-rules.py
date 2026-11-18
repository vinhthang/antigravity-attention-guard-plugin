#!/usr/bin/env python3
import json
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent, scan_transcript_header
from context_boundary import EVIDENCE_BOUNDARY, materialize_context_pointer
from ledger import Ledger


def extract_subagents(args: dict) -> list:
    """Extract list of subagent dicts from either Subagents list or flat invoke_subagent args."""
    if not isinstance(args, dict):
        return []
    if "Subagents" in args and isinstance(args["Subagents"], list):
        return args["Subagents"]
    if "Prompt" in args or "TypeName" in args or "Role" in args:
        return [args]
    return []


def _read_rule_template(base_dir: str, filename: str) -> str:
    for subdir in ("templates", "rules"):
        candidate = os.path.abspath(os.path.join(base_dir, "..", subdir, filename))
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
    return ""


def main(argv=None, stdin=None, stdout=None):
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    def emit(data):
        if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
            stdout.write(json.dumps({"decision": "allow", "overwrite": data.get("overwrite", {})}) + "\n")
        else:
            stdout.write(json.dumps(data) + "\n")

    try:
        input_data = stdin.read()
        if not input_data:
            emit({"decision": "allow"})
            return
        payload = json.loads(input_data)
        tool_call = payload.get("toolCall", {})
        if tool_call.get("name") not in ("invoke_subagent", "default_api:invoke_subagent"):
            emit({"decision": "allow"})
            return

        args = tool_call.get("args", {})
        is_flat = isinstance(args, dict) and "Subagents" not in args and (
            "Prompt" in args or "TypeName" in args or "Role" in args
        )
        subagents = extract_subagents(args)
        if not subagents:
            emit({"decision": "allow"})
            return

        script_dir = os.path.dirname(__file__)
        exec_rules_text = _read_rule_template(script_dir, "EXECUTOR.md")
        coord_rules_text = _read_rule_template(script_dir, "COORDINATOR.md")

        parent_conv_id = payload.get("conversationId", "unknown")
        step_idx = payload.get("stepIdx", 0)
        turn_id = scan_transcript_header(payload.get("transcriptPath", "")).get("turn_id", 0)
        ledger = Ledger()
        is_sub, _, _, _, _ = is_subagent(payload, ledger=ledger)

        for sa in subagents:
            type_name = str(sa.get("TypeName") or "").strip()
            if is_sub:
                child_may_delegate, child_depth = False, 0
            else:
                child_may_delegate = type_name in ("DeepCoder", "DeepInvestigator")
                child_depth = 1 if child_may_delegate else 0

            token = str(uuid.uuid4())
            try:
                ledger.issue_token(
                    token,
                    may_delegate=child_may_delegate,
                    remaining_depth=child_depth,
                    parent_conv_id=parent_conv_id,
                )
                payload_data = {
                    "token": token,
                    "tool": "invoke",
                    "valid_handoff": True,
                    "may_delegate": child_may_delegate,
                    "remaining_depth": child_depth,
                    "parent_conv_id": parent_conv_id,
                    "parent_turn_id": turn_id,
                }
                ledger.insert_event(
                    parent_conv_id,
                    str(turn_id),
                    "PreToolUse",
                    str(step_idx),
                    token,
                    "WORK_PREPARED",
                    json.dumps(payload_data),
                )
            except Exception:
                emit({"decision": "deny", "reason": "Attention Guard: Failed to issue cryptographic token to subagent cache."})
                return

            raw_prompt = sa.get("Prompt", "")
            effective_prompt, _ = materialize_context_pointer(raw_prompt, token)
            role_rules = coord_rules_text if child_may_delegate else exec_rules_text
            injected_text = f"{role_rules}\n\n{EVIDENCE_BOUNDARY}" if role_rules else EVIDENCE_BOUNDARY
            injected = f"\n\n--- INJECTED RULES ---\n{injected_text}"
            sa["Prompt"] = f"[ANTIGRAVITY_TOKEN:{token}]\n\n{effective_prompt}{injected}"

        if is_flat:
            emit({"decision": "allow", "overwrite": subagents[0]})
        else:
            emit({"decision": "allow", "overwrite": {"Subagents": subagents}})
    except Exception as exc:
        emit({"decision": "deny", "reason": f"Attention Guard Exception in inject-rules: {exc}"})


if __name__ == "__main__":
    main()
