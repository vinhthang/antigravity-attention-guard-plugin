#!/usr/bin/env python3
import sys
import json
import shutil
import re

# Commands that benefit from RTK output compression
RTK_COMPATIBLE = [
    "kubectl", "git", "docker", "docker-compose", "podman",
    "mvn", "gradle", "./gradlew", "go ", "cargo", "rustc",
    "npm", "npx", "pnpm", "yarn",
    "pip ", "pip3", "uv ", "ruff", "pytest",
    "aws", "oci", "gcloud", "az ",
    "terraform", "tofu",
    "helm", "istioctl",
    "curl", "wget",
    "brew",
    "lsof", "ps ", "top", "htop",
    "find ", "rg ", "grep", "ag ",
    "tree", "ls ", "ls\t",
    "glab", "gh ",
    "make", "cmake",
]


def should_prepend_rtk(cmd):
    """Check if the command should have RTK prepended."""
    cmd_stripped = cmd.strip()
    if not cmd_stripped:
        return False
    # Skip if command already starts with rtk or pipes to rtk
    if cmd_stripped.lower().startswith("rtk") or "| rtk" in cmd_stripped.lower():
        return False
    # Check if command starts with an allowlisted prefix, even if environment variables are prepended
    pattern = re.compile(
        r'^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+)*(' + '|'.join(re.escape(p) for p in RTK_COMPATIBLE) + ')',
        re.IGNORECASE
    )
    return bool(pattern.match(cmd_stripped))


def main():
    try:
        # Skip RTK enforcement if rtk is not installed in the environment
        if shutil.which("rtk") is None:
            print(json.dumps({"decision": "allow"}))
            return

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

        # Check if the command should have RTK prepended
        if not should_prepend_rtk(command_line):
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
