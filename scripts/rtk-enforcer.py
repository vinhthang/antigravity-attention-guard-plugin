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
    "tree", "ls ",
    "glab", "gh ",
    "make", "cmake",
]


def split_env_prefix(cmd):
    """Split leading environment variable assignments and skippable prefixes from the command."""
    match = re.match(r'^((?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+|sudo\s+|time\s+|nice\s+)*)(.*)', cmd)
    if match:
        return match.group(1), match.group(2)
    return "", cmd

def should_prepend_rtk(cmd):
    prefix, core_cmd = split_env_prefix(cmd)
    if not core_cmd:
        return False
    if "| rtk" in cmd:
        return False
    for allow in RTK_COMPATIBLE:
        if core_cmd.startswith(allow):
            return True
    return False

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
        prefix, core_cmd = split_env_prefix(command_line)
        rtk_command = f"{prefix}rtk {core_cmd}"
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
