#!/usr/bin/env python3
import sys
import os
import json
import subprocess

def main(argv=None, stdin=None, stdout=None):
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout
    try:
        raw_input = stdin.read()
        if not raw_input.strip():
            stdout.write(json.dumps({"decision": "allow"}) + "\n")
            return
        payload = json.loads(raw_input)
    except Exception as exc:
        _ = exc
        stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return

    tool_call = payload.get("toolCall", {})
    args = tool_call.get("args", {})
    if os.environ.get("AGY_DISABLE_JSON_GATE") == "1":
        stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return
    message_raw = args.get("Message") if args.get("Message") is not None else args.get("message")
    
    if isinstance(message_raw, dict):
        message_data = message_raw
    elif isinstance(message_raw, str):
        msg_str = message_raw.strip()
        if msg_str.startswith('"') and msg_str.endswith('"') and len(msg_str) >= 2:
            try:
                decoded = json.loads(msg_str)
                if isinstance(decoded, str):
                    msg_str = decoded.strip()
                elif isinstance(decoded, dict):
                    msg_str = json.dumps(decoded)
            except Exception as dec_err:
                _ = dec_err
        try:
            message_data = json.loads(msg_str)
        except Exception as json_err:
            _ = json_err
            stdout.write(json.dumps({
                "decision": "deny",
                "reason": "Handoff MUST be valid JSON. No conversational fluff."
            }) + "\n")
            return
    else:
        stdout.write(json.dumps({
            "decision": "deny",
            "reason": "Handoff MUST be valid JSON. No conversational fluff."
        }) + "\n")
        return

    if not isinstance(message_data, dict):
        stdout.write(json.dumps({
            "decision": "deny",
            "reason": "Handoff MUST be valid JSON. No conversational fluff."
        }) + "\n")
        return

    verify_cmd = message_data.get("verify_cmd")
    if verify_cmd is not None:
        if not isinstance(verify_cmd, str):
            stdout.write(json.dumps({
                "decision": "deny",
                "reason": "Verification Failed: verify_cmd must be a string"
            }) + "\n")
            return
        try:
            res = subprocess.run(
                verify_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=15
            )
            if res.returncode != 0:
                err_output = res.stderr.strip() or res.stdout.strip() or f"exit code {res.returncode}"
                stdout.write(json.dumps({
                    "decision": "deny",
                    "reason": f"Verification Failed: {err_output}"
                }) + "\n")
                return
        except subprocess.TimeoutExpired:
            stdout.write(json.dumps({
                "decision": "deny",
                "reason": "Verification Failed: command timed out after 15s"
            }) + "\n")
            return
        except Exception as e:
            stdout.write(json.dumps({
                "decision": "deny",
                "reason": f"Verification Failed: {str(e)}"
            }) + "\n")
            return

    stdout.write(json.dumps({"decision": "allow"}) + "\n")

if __name__ == "__main__":
    main()
