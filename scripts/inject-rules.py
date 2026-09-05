#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import uuid
import time
from common import get_cache_dir, is_subagent, get_turn_state
from ledger import Ledger

def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout

    def emit(data):
        stdout.write(json.dumps(data) + "\n")

    try:
        input_data = stdin.read()
        if not input_data:
            emit({"decision": "allow"})
            return

        payload = json.loads(input_data)

        executor_rule = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules", "EXECUTOR.md"))
        coordinator_rule = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules", "COORDINATOR.md"))

        exec_rules_text = ""
        if os.path.exists(executor_rule):
            with open(executor_rule, "r") as f:
                exec_rules_text = f.read()

        coord_rules_text = ""
        if os.path.exists(coordinator_rule):
            with open(coordinator_rule, "r") as f:
                coord_rules_text = f.read()

        tool_call = payload.get("toolCall", {})
        if tool_call.get("name") == "invoke_subagent":
            args = tool_call.get("args", {})
            subagents = args.get("Subagents", [])
            parent_conv_id = payload.get("conversationId", "unknown")
            step_idx = payload.get("stepIndex", 0)
            
            turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))

            is_sub, current_may_delegate, current_depth, _, _ = is_subagent(payload)
            ledger = Ledger()

            for sa in subagents:
                type_name = sa.get("TypeName", "")
                
                if is_sub:
                    child_may_delegate = False
                    child_depth = 0
                else:
                    child_may_delegate = type_name in ["DeepCoder", "DeepInvestigator"]
                    child_depth = 1 if child_may_delegate else 0

                token = str(uuid.uuid4())
                try:
                    with ledger._get_connection() as conn:
                        conn.execute("INSERT INTO tokens (token_id, created_at) VALUES (?, ?)", (token, time.time()))
                    
                    payload_data = {
                        "token": token,
                        "may_delegate": child_may_delegate,
                        "remaining_depth": child_depth,
                        "parent_conv_id": parent_conv_id,
                        "parent_turn_id": turn_id
                    }
                    ledger.insert_event(parent_conv_id, str(turn_id), "PreToolUse", str(step_idx), token, "WORK_PREPARED", json.dumps(payload_data))
                except Exception:
                    emit({"decision": "deny", "reason": "Attention Guard: Failed to issue cryptographic token to subagent cache."})
                    return
                
                injected_text = coord_rules_text if child_may_delegate else exec_rules_text
                injected = ("\n\n--- INJECTED RULES ---\n" + injected_text) if injected_text else ""
                sa["Prompt"] = f"[ANTIGRAVITY_TOKEN:{token}]\n\n" + sa.get("Prompt", "") + injected

            emit({
                "decision": "allow",
                "overwrite": {
                    "Subagents": subagents
                }
            })
            return

        emit({"decision": "allow"})
    except Exception:
        emit({"decision": "allow"})


if __name__ == "__main__":
    main()
