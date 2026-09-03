#!/usr/bin/env python3
import sys
import json
import shutil
import re

# Commands that benefit from RTK output compression
# No trailing spaces needed — word boundary matching handles disambiguation
RTK_COMPATIBLE = [
    "kubectl", "git", "docker-compose", "docker", "podman",
    "mvn", "gradle", "./gradlew", "go", "cargo", "rustc",
    "npm", "npx", "pnpm", "yarn",
    "pip3", "pip", "uv", "ruff", "pytest",
    "aws", "oci", "gcloud", "az",
    "terraform", "tofu",
    "helm", "istioctl",
    "curl", "wget",
    "brew",
    "lsof", "ps", "top", "htop",
    "find", "rg", "grep", "ag",
    "tree", "ls",
    "glab", "gh",
    "make", "cmake",
]

# Build regex: sort longest-first to prevent partial matches (docker-compose before docker)
# Match command followed by whitespace or end-of-string
_RTK_PATTERN = re.compile(
    r'^(' + '|'.join(re.escape(cmd) for cmd in sorted(RTK_COMPATIBLE, key=len, reverse=True)) + r')(\s|$)',
)


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
    if "| rtk" in cmd or core_cmd.startswith("rtk "):
        return False
    return bool(_RTK_PATTERN.match(core_cmd))


def main():
    try:
        if shutil.which("rtk") is None:
            print(json.dumps({"decision": "allow"}))
            return

        raw_payload = sys.stdin.read()
        if not raw_payload or not raw_payload.strip():
            print(json.dumps({"decision": "allow"}))
            return

        data = json.loads(raw_payload)

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

        if not should_prepend_rtk(command_line):
            print(json.dumps({"decision": "allow"}))
            return

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
