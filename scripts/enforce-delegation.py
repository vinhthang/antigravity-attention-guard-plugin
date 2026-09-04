#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import re
import time
from common import is_subagent, get_cache_dir


MCP_READ_ALLOWLIST = {
    "codegraph_search", "codegraph_context", "codegraph_callers", 
    "codegraph_callees", "codegraph_node", "codegraph_explore",
    "codegraph_status", "codegraph_files", "codegraph_impact",
    "resolve-library-id", "query-docs",
    "sequentialthinking",
    "read_file", "read_text_file", "read_media_file", 
    "read_multiple_files", "list_directory", "list_directory_with_sizes",
    "directory_tree", "search_files", "get_file_info", "list_allowed_directories",
}


# Read-only commands the primary agent can run directly.
# These produce bounded output unlikely to cause attention dilution.
# RTK will further compress output for RTK-compatible commands.
PRIMARY_SAFE_COMMANDS = [
    # Version control (read-only)
    "git status", "git branch", "git log", "git diff", "git show",
    "git stash list", "git remote", "git tag", "git rev-parse",
    # Search (bounded by pattern matching)
    "rg ", "grep ", "ag ", "ack ",
    # File inspection (bounded output)
    "wc ", "head ", "tail ", "file ", "stat ",
    # Directory listing
    "ls", "tree",
    # System info (tiny output)
    "echo ", "date", "whoami", "pwd", "which ", "type ",
    # Already compressed
    "rtk ",
    # Test runners (output compressed by RTK)
    "pytest", "python3 -m pytest",
]

_PRIMARY_SAFE_RE = re.compile(
    r'^(' + '|'.join(re.escape(cmd.rstrip()) for cmd in sorted(PRIMARY_SAFE_COMMANDS, key=len, reverse=True)) + r')(\s|$)',
)

def is_safe_primary_command(command_line):
    """Check if a command is safe for the primary agent to run directly."""
    # Strip env vars, sudo, time, nice prefixes
    match = re.match(r'^(?:[A-Za-z_][A-Za-z0-9_]*=\S+\s+|sudo\s+|time\s+|nice\s+)*(.*)', command_line)
    core_cmd = match.group(1) if match else command_line
    if not core_cmd:
        return False
    return bool(_PRIMARY_SAFE_RE.match(core_cmd))





def is_artifact_path(target_file, artifact_dir):
    """Check if target_file is within the artifact (brain/) directory.
    Uses realpath to prevent symlink escapes.
    """
    if not target_file:
        return False
    norm_target = os.path.realpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.realpath(os.path.abspath(artifact_dir))
        if norm_target.startswith(norm_artifact + os.sep) or norm_target == norm_artifact:
            return True
    # Fallback: require brain/<uuid>/ pattern
    return bool(re.search(r'/brain/[0-9a-f-]{36}/', norm_target))


def main():
    try:
        raw_payload = sys.stdin.read()
        if not raw_payload or not raw_payload.strip():
            print(json.dumps({"decision": "allow"}))
            return

        data = json.loads(raw_payload)

        # Allow subagents to execute freely
        if is_subagent(data):
            print(json.dumps({"decision": "allow"}))
            return

        # Allow Primary Agent to write artifacts
        tool_call = data.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile", "") or args.get("target_file", "") or args.get("path", "")
        artifact_dir = data.get("artifactDirectoryPath", "")

        if is_artifact_path(target_file, artifact_dir):
            print(json.dumps({"decision": "allow"}))
            return

        # Allow Primary Agent to generate images (used for artifacts and UI mockups)
        if tool_name == "generate_image":
            print(json.dumps({"decision": "allow"}))
            return

        # Allow Primary Agent to run bounded, read-only commands
        if tool_name == "run_command":
            command_line = args.get("CommandLine", "")
            if is_safe_primary_command(command_line):
                print(json.dumps({"decision": "allow"}))
                return

        # Enforce MCP Tool Allowlist for Primary Agent
        if tool_name == "call_mcp_tool":
            mcp_tool_name = args.get("ToolName", "")
            if mcp_tool_name in MCP_READ_ALLOWLIST:
                print(json.dumps({"decision": "allow"}))
                return
            
            print(json.dumps({
                "decision": "deny", 
                "reason": f"Attention Dilution Guard: The Primary Agent is restricted to read-only MCP tools. The tool '{mcp_tool_name}' must be delegated to a subagent."
            }))
            return

        # Block Primary Agent from direct code execution and file modifications
        print(json.dumps({
            "decision": "deny",
            "reason": (
                "Attention Dilution Guard: The Primary Agent is restricted to planning "
                "and artifact creation. Direct code modification and shell execution must be "
                "delegated to a subagent."
            )
        }))
    except json.JSONDecodeError:
        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
