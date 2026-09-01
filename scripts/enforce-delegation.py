#!/usr/bin/env python3
import sys
import json

def main():
    try:
        payload = sys.stdin.read()
        if not payload:
            print(json.dumps({"decision": "allow"}))
            return
            
        payload_lower = payload.lower()
        
        # Allow flash subagents
        if 'flash' in payload_lower:
            print(json.dumps({"decision": "allow"}))
            return
            
        # Allow primary agent to write to artifacts (e.g. implementation_plan.md)
        try:
            data = json.loads(payload)
            tool_name = data.get("toolCall", {}).get("name", "")
            args = data.get("toolCall", {}).get("args", {})
            target_file = args.get("TargetFile", "") or args.get("TargetFile", "") # handle both cases
            # some tools use different arg names, just check if 'brain/' is in payload for simplicity
            if 'brain/' in payload_lower:
                print(json.dumps({"decision": "allow"}))
                return
        except Exception:
            pass

        print(json.dumps({
            "decision": "deny", 
            "reason": "Attention Dilution detected! Violation of delegation rules: The Primary Agent is physically blocked from executing code or terminal commands. You MUST stop, read the agent delegation instructions, and do the work again by delegating to a subagent (Model: 'flash')."
        }))
    except Exception:
        print(json.dumps({"decision": "allow"}))

if __name__ == "__main__":
    main()
