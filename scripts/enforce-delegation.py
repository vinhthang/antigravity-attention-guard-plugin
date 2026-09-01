#!/usr/bin/env python3
import sys
import json

def main():
    try:
        payload = sys.stdin.read()
        if not payload:
            print(json.dumps({"decision": "allow"}))
            return
            
        if 'flash' in payload.lower():
            print(json.dumps({"decision": "allow"}))
        else:
            print(json.dumps({
                "decision": "deny", 
                "reason": "Attention Dilution detected! Violation of delegation rules: The Primary Agent is physically blocked from executing code or terminal commands. You MUST stop, read the agent delegation instructions, and do the work again by delegating to a subagent (Model: 'flash')."
            }))
    except Exception:
        print(json.dumps({"decision": "allow"}))

if __name__ == "__main__":
    main()
