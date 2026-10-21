#!/usr/bin/env python3
import sys, os, json, uuid, time
sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent, get_turn_state, get_primary_model, is_thinking_model
from ledger import Ledger
from context_boundary import EVIDENCE_BOUNDARY, materialize_context_pointer

def extract_subagents(args: dict) -> list:
    """Extract list of subagent dicts from either Subagents list or flat invoke_subagent args."""
    if not isinstance(args, dict):
        return []
    if "Subagents" in args and isinstance(args["Subagents"], list):
        return args["Subagents"]
    if "Prompt" in args or "TypeName" in args or "Role" in args:
        return [args]
    return []

def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout
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
        executor_rule = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules", "EXECUTOR.md"))
        coordinator_rule = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules", "COORDINATOR.md"))
        exec_rules_text = open(executor_rule, "r").read() if os.path.exists(executor_rule) else ""
        coord_rules_text = open(coordinator_rule, "r").read() if os.path.exists(coordinator_rule) else ""
        tool_call = payload.get("toolCall", {})
        if tool_call.get("name") in ["invoke_subagent", "default_api:invoke_subagent"]:
            args = tool_call.get("args", {})
            is_flat = "Subagents" not in args and ("Prompt" in args or "TypeName" in args or "Role" in args)
            subagents = extract_subagents(args)
            if not subagents:
                emit({"decision": "allow"})
                return
            parent_conv_id = payload.get("conversationId", "unknown")
            step_idx = payload.get("stepIdx", 0)
            turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))
            is_sub, current_may_delegate, current_depth, _, _ = is_subagent(payload)
            parent_is_thinking = is_thinking_model(get_primary_model(payload))
            ledger = Ledger()
            for sa in subagents:
                type_name = str(sa.get("TypeName") or "").strip()
                role_lower = str(sa.get("Role") or "").strip().lower()
                is_traceability_auditor = (type_name.lower() == "traceability-auditor" or "traceability" in role_lower)
                if is_traceability_auditor:
                    model_val_lower = str(sa.get("Model") or "").strip().lower()
                    if model_val_lower in ("flash", "flash_lite"):
                        emit({"decision": "deny", "reason": "Attention Guard: Traceability auditor subagent must use Opus ('pro' or 'inherit'), never 'flash'."})
                        return
                    if sa.get("Model") in (None, ""):
                        sa["Model"] = "pro"
                else:
                    if parent_is_thinking:
                        model_val = sa.get("Model")
                        if model_val in (None, "", "inherit"):
                            sa["Model"] = "flash"
                if is_sub:
                    child_may_delegate, child_depth = False, 0
                else:
                    child_may_delegate = type_name in ["DeepCoder", "DeepInvestigator"]
                    child_depth = 1 if child_may_delegate else 0
                token = str(uuid.uuid4())
                try:
                    with ledger._get_connection() as conn:
                        now = time.time()
                        conn.execute("INSERT INTO tokens (token_id, created_at) VALUES (?, ?)", (token, now))
                        conn.execute("INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx) VALUES (?, ?, ?, ?, ?, ?, ?)", (token, 'ACTIVE', now, now, parent_conv_id, str(turn_id), str(step_idx)))
                    payload_data = {"token": token, "tool": "invoke", "valid_handoff": True, "may_delegate": child_may_delegate, "remaining_depth": child_depth, "parent_conv_id": parent_conv_id, "parent_turn_id": turn_id}
                    ledger.insert_event(parent_conv_id, str(turn_id), "PreToolUse", str(step_idx), token, "WORK_PREPARED", json.dumps(payload_data))
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
            return
        emit({"decision": "allow"})
    except Exception as exc:
        emit({"decision": "deny", "reason": f"Attention Guard Exception in inject-rules: {exc}"})

if __name__ == "__main__": main()
