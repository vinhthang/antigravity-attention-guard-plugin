#!/usr/bin/env python3
import sys
import json
import os
import time


def main():
    try:
        input_data = sys.stdin.read()
        if not input_data:
            print(json.dumps({"decision": "allow"}))
            return

        payload = json.loads(input_data)

        # Read the plugin's own AGENTS.md (relative to this script)
        agents_rule = os.path.join(os.path.dirname(__file__), "..", "rules", "AGENTS.md")
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
            base_seq = int(time.time() * 1000)
            for i, sa in enumerate(subagents):
                marker = f"[ANTIGRAVITY_SUBAGENT:{parent_conv_id}:{base_seq + i}]"
                sa["Prompt"] = sa.get("Prompt", "") + injected + f"\n\n{marker}"

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
