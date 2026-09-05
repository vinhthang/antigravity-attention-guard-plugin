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
    ("server-filesystem", "read_media_file"),
    ("server-filesystem", "list_directory"), ("server-filesystem", "list_directory_with_sizes"),
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


def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout

    def emit(data):
        stdout.write(json.dumps(data) + "\n")

    try:
        raw_payload = stdin.read()
        if not raw_payload or not raw_payload.strip():
            emit({"decision": "allow"})
            return

        data = json.loads(raw_payload)

        # Allow subagents to execute freely
        is_sub, may_delegate = is_subagent(data)
        if is_sub:
            tool_call = data.get("toolCall", {})
            tool_name = tool_call.get("name", "")
            if tool_name in ["invoke_subagent", "manage_subagents", "default_api:invoke_subagent", "default_api:manage_subagents"]:
                if not may_delegate:
                    emit({"decision": "deny", "reason": "Attention Dilution Guard: Subagents are forbidden from delegating tasks further. Do not invoke or manage subagents."})
                    return
            emit({"decision": "allow"})
            return

        # Allow Primary Agent to write artifacts
        tool_call = data.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile", "")
        if target_file and tool_name in ["write_to_file", "replace_file_content", "default_api:write_to_file", "default_api:replace_file_content"]:
            artifact_dir = data.get("artifactDirectoryPath", "")
            if artifact_dir and is_artifact_path(target_file, artifact_dir):
                emit({"decision": "allow"})
                return

        # Allow Primary Agent to generate images (used for artifacts and UI mockups)
        if tool_name in ["generate_image", "default_api:generate_image"]:
            emit({"decision": "allow"})
            return

        # Allow Primary Agent to run bounded, read-only commands
        if tool_name in ["run_command", "default_api:run_command"]:
            emit({"decision": "deny", "reason": "Attention Dilution Guard: The Primary Agent is forbidden from executing shell commands. You must delegate to a subagent."})
            return

        # Allow coordination and basic read tools
        ALLOWED_TOOLS = {
            "view_file", "grep_search", "list_dir", "find_by_name", "search_web", "read_url_content",
            "default_api:view_file", "default_api:grep_search", "default_api:list_dir", "default_api:find_by_name", "default_api:search_web", "default_api:read_url_content",
            "invoke_subagent", "manage_subagents", "send_message", "manage_task", "schedule",
            "ask_question", "ask_permission", "list_resources", "read_resource",
            "default_api:invoke_subagent", "default_api:manage_subagents", "default_api:send_message", "default_api:manage_task", "default_api:schedule",
            "default_api:ask_question", "default_api:ask_permission", "default_api:list_resources", "default_api:read_resource"
        }
        
        if tool_name in ALLOWED_TOOLS:
            emit({"decision": "allow"})
            return

        if tool_name in ["call_mcp_tool", "default_api:call_mcp_tool"]:
            mcp_tool_name = args.get("ToolName", "")
            server_name = args.get("ServerName", "")
            if (server_name, mcp_tool_name) in MCP_READ_ALLOWLIST:
                emit({"decision": "allow"})
                return

            emit({
                "decision": "deny",
                "reason": f"Attention Dilution Guard: The Primary Agent is restricted to read-only MCP tools. The tool '{mcp_tool_name}' must be delegated to a subagent."
            })
            return

        # Block Primary Agent from direct code execution and file modifications
        emit({
            "decision": "deny",
            "reason": (
                "Attention Dilution Guard: The Primary Agent is restricted to planning "
                "and artifact creation. Direct code modification and shell execution must be "
                "delegated to a subagent."
            )
        })
    except json.JSONDecodeError:
        emit({"decision": "deny"})
    except Exception:
        emit({"decision": "deny"})


if __name__ == "__main__":
    main()
