#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import re
import time
from common import is_subagent, get_cache_dir


MCP_READ_ALLOWLIST = {
    ("codegraph", "codegraph_search"), ("codegraph", "codegraph_context"),
    ("codegraph", "codegraph_callers"), ("codegraph", "codegraph_callees"),
    ("codegraph", "codegraph_node"), ("codegraph", "codegraph_explore"),
    ("codegraph", "codegraph_status"), ("codegraph", "codegraph_files"),
    ("codegraph", "codegraph_impact"),
    ("context7", "resolve-library-id"), ("context7", "query-docs"),
    ("sequential-thinking", "sequentialthinking"),
    ("server-filesystem", "read_file"), ("server-filesystem", "read_text_file"),
    ("server-filesystem", "read_media_file"), ("server-filesystem", "read_multiple_files"),
    ("server-filesystem", "list_directory"), ("server-filesystem", "list_directory_with_sizes"),
    ("server-filesystem", "directory_tree"), ("server-filesystem", "search_files"),
    ("server-filesystem", "get_file_info"), ("server-filesystem", "list_allowed_directories")
}


def is_artifact_path(target_file, artifact_dir):
    """Check if target_file is within the artifact (brain/) directory.
    Uses realpath to prevent symlink escapes.
    """
    if not target_file:
        return False
    norm_target = os.path.realpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.realpath(os.path.abspath(artifact_dir))
        if os.path.commonpath([norm_target, norm_artifact]) == norm_artifact:
            return True
    return False


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
        target_file = args.get("TargetFile", "")
        if target_file and tool_name in ["write_to_file", "replace_file_content"]:
            artifact_dir = data.get("artifactDirectoryPath", "")
            if artifact_dir and is_artifact_path(target_file, artifact_dir):
                print(json.dumps({"decision": "allow"}))
                return

        # Allow Primary Agent to generate images (used for artifacts and UI mockups)
        if tool_name == "generate_image":
            print(json.dumps({"decision": "allow"}))
            return

        # Allow Primary Agent to run bounded, read-only commands
        if tool_name == "run_command":
            print(json.dumps({"decision": "deny", "reason": "Attention Dilution Guard: The Primary Agent is forbidden from executing shell commands. You must delegate to a subagent."}))
            return

        # Enforce MCP Tool Allowlist for Primary Agent
        if tool_name == "call_mcp_tool":
            mcp_tool_name = args.get("ToolName", "")
            server_name = args.get("ServerName", "")
            if (server_name, mcp_tool_name) in MCP_READ_ALLOWLIST:
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
        print(json.dumps({"decision": "deny"}))
    except Exception:
        print(json.dumps({"decision": "deny"}))


if __name__ == "__main__":
    main()
