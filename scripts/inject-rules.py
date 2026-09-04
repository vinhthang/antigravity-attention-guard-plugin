#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import get_cache_dir

def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(input_data)

        # Read the plugin's own AGENTS.md
        agents_rule = os.path.join(os.path.dirname(__file__), "..", "rules", "EXECUTOR.md")
        agents_rule = os.path.abspath(agents_rule)

        rules_text = ""
        if os.path.exists(agents_rule):
            with open(agents_rule, "r") as f:
                rules_text = f.read()

        injected = ("\n\n--- INJECTED RULES ---\n" + rules_text) if rules_text else ""

        tool_call = payload.get("toolCall", {})
        if tool_call.get("name") == "invoke_subagent":
            args = tool_call.get("args", {})
            subagents = args.get("Subagents", [])
            parent_conv_id = payload.get("conversationId", "unknown")

            import uuid

            # Issue a token for each child subagent
            cache_dir = get_cache_dir()

            for sa in subagents:
                token = str(uuid.uuid4())
                try:
                    token_file = os.path.join(cache_dir, f"agy_issued_token_{token}")
                    with open(token_file, "w") as f:
                        json.dump({"issuer": parent_conv_id, "recipient": None}, f)
                except Exception:
                    print(json.dumps({"decision": "deny", "reason": "Attention Guard: Failed to issue cryptographic token to subagent cache."}))
                    return
                sa["Prompt"] = f"[ANTIGRAVITY_TOKEN:{token}]\n\n" + sa.get("Prompt", "") + injected

            print(json.dumps({
                "decision": "allow",
                "overwrite": {
                    "Subagents": subagents
                }
            }))
            return

        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
