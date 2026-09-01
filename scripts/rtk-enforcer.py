#!/usr/bin/env python3
import sys
import json

# Commands that are too simple or don't benefit from RTK compression
SKIP_PREFIXES = [
    "rtk",        # already using rtk
    "echo",       # simple output
    "mkdir",      # file operations
    "cp ", "cp\t",
    "mv ", "mv\t",
    "rm ", "rm\t",
    "chmod",
    "touch",
    "cat ", "cat\t",
    "export",
    "source",
    "cd ", "cd\t",
    "which",
    "true",
    "false",
    "sleep",
    "kill",
    "pip",
    "pip3",
    "npm install",
    "pnpm install",
    "brew install",
    "python3 -c",
    "python -c",
]


def should_skip(cmd):
    """Check if the command should skip RTK enforcement."""
    cmd_stripped = cmd.strip()
    # Skip if command already pipes to rtk
    if "| rtk" in cmd_stripped:
        return True
    # Skip if command starts with a known simple prefix
    cmd_lower = cmd_stripped.lower()
    for prefix in SKIP_PREFIXES:
        if cmd_lower.startswith(prefix):
            return True
    return False


def main():
    try:
        raw_payload = sys.stdin.read()
        if not raw_payload or not raw_payload.strip():
            print(json.dumps({"decision": "allow"}))
            return

        data = json.loads(raw_payload)

        # Only enforce RTK on run_command tool calls
        tool_call = data.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        if tool_name != "run_command":
            print(json.dumps({"decision": "allow"}))
            return

        args = tool_call.get("args", {})
        command_line = args.get("CommandLine", "")
        if not command_line:
            print(json.dumps({"decision": "allow"}))
            return

        # Skip commands that don't benefit from RTK
        if should_skip(command_line):
            print(json.dumps({"decision": "allow"}))
            return

        # Prepend rtk to the command
        rtk_command = f"rtk {command_line}"
        print(json.dumps({
            "decision": "allow",
            "overwrite": {
                "CommandLine": rtk_command
            }
        }))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
