#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import re
import time
from common import is_subagent, get_cache_dir


# Verb prefixes that indicate a mutating/write MCP tool
WRITE_VERB_PREFIXES = (
    "write", "edit", "create", "update", "delete", "remove",
    "push", "move", "fork", "insert", "modify", "set", "put",
    "patch", "deploy", "add", "transition", "fill",
    "merge", "submit", "approve", "publish", "archive", "send", "commit", "upload",
)

MCP_SCHEMA_DIR = os.path.expanduser("~/.gemini/antigravity/mcp")
MCP_CACHE_TTL = 300  # seconds


def discover_mcp_write_tools():
    """Scan MCP schema directories to discover write/mutating tools.
    
    Caches the result in a temp file for 5 minutes to avoid
    repeated filesystem scans on every hook invocation.
    """
    cache_file = os.path.join(get_cache_dir(), "agy_mcp_write_tools.json")
    
    # Check cache
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r") as f:
                cached = json.load(f)
            if time.time() - cached.get("timestamp", 0) < MCP_CACHE_TTL:
                return set(cached.get("tools", []))
        except Exception:
            pass
    
    # Scan MCP schema directories
    write_tools = set()
    if os.path.exists(MCP_SCHEMA_DIR):
        try:
            for server_name in os.listdir(MCP_SCHEMA_DIR):
                server_dir = os.path.join(MCP_SCHEMA_DIR, server_name)
                if not os.path.isdir(server_dir):
                    continue
                for filename in os.listdir(server_dir):
                    if not filename.endswith(".json"):
                        continue
                    tool_name = filename[:-5]  # Remove .json
                    tool_lower = tool_name.lower()
                    for prefix in WRITE_VERB_PREFIXES:
                        if tool_lower.startswith(prefix):
                            write_tools.add(tool_lower)
                            break
        except Exception:
            pass
    
    # Write cache
    try:
        with open(cache_file, "w") as f:
            json.dump({"timestamp": time.time(), "tools": list(write_tools)}, f)
    except Exception:
        pass
    
    return write_tools


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

        # Check if this is an MCP tool call
        if tool_name == "call_mcp_tool":
            mcp_tool = args.get("ToolName", "").lower()
            mcp_write_tools = discover_mcp_write_tools()
            if mcp_tool not in mcp_write_tools:
                print(json.dumps({"decision": "allow"}))
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
