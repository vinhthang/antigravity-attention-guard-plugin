import sys, os
sys.path.insert(0, os.path.dirname(__file__))
#!/usr/bin/env python3
from common import is_subagent, get_cache_dir
import sys
import json
import os
import re
import time


# Verb prefixes that indicate a mutating/write MCP tool
WRITE_VERB_PREFIXES = (
    "write", "edit", "create", "update", "delete", "remove",
    "push", "move", "fork", "insert", "modify", "set", "put",
    "patch", "deploy", "add", "transition", "fill",
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
                    # Check if tool name starts with a write verb prefix
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
    """Check if target_file is within the artifact (brain/) directory."""
    if not target_file:
        return False
    norm_target = os.path.normpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.normpath(os.path.abspath(artifact_dir))
        if norm_target.startswith(norm_artifact):
            return True
    # Fallback: require brain/<uuid>/ pattern (Antigravity conversation IDs are UUIDs)
    return bool(re.search(r'/brain/[0-9a-f-]{36}/', norm_target))


    idx = 0
    blob_len = len(blob)
    while idx < blob_len:
        key = 0
        shift = 0
        while idx < blob_len:
            byte = blob[idx]
            idx += 1
            key |= (byte & 0x7F) << shift
            if not (byte & 0x80):
                break
            shift += 7
            if shift > 64:
                return False

        field_number = key >> 3
        wire_type = key & 0x07

        if field_number == 5:
            return True

        if wire_type == 0:  # Varint
            while idx < blob_len and (blob[idx] & 0x80):
                idx += 1
            idx += 1
        elif wire_type == 1:  # 64-bit
            idx += 8
        elif wire_type == 2:  # Length-delimited
            length = 0
            shift = 0
            while idx < blob_len:
                byte = blob[idx]
                idx += 1
                length |= (byte & 0x7F) << shift
                if not (byte & 0x80):
                    break
                shift += 7
                if shift > 64:
                    return False
            idx += length
        elif wire_type == 5:  # 32-bit
            idx += 4
        else:
            break
    return False


def is_subagent(conversation_id, model_name="", transcript_path=""):
    """Deterministically detect if the current agent is a subagent.

    1. Checks transcript marker [ANTIGRAVITY_SUBAGENT: in first 8KB if transcriptPath is provided.
    2. Checks SQLite databases (index.db, antigravity.db, or {conversation_id}.db)
       using a read-only URI (mode=ro, uri=True) to prevent SQLITE_BUSY deadlocks.
    3. Wraps the connection in a `with sqlite3.connect(...) as conn:` block.
    4. Queries the table containing trajectory_metadata for conversation_id.
    5. Checks if the protobuf blob contains Field 5 (parent_conversation_id).
    6. Gracefully falls back to '"flash" in model_name' if the DB is missing,
       locked, or parsing fails.
    """
    if isinstance(conversation_id, dict):
        data = conversation_id
        conversation_id = data.get("conversationId", "")
        model_name = data.get("modelName", "")
        transcript_path = data.get("transcriptPath", "")

    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "rb") as f:
                chunk = f.read(8192)
            if b"[ANTIGRAVITY_SUBAGENT:" in chunk:
                return True
        except Exception:
            pass

    fallback = "flash" in (model_name or "").lower()

    try:
        candidate_paths = [
            os.path.expanduser("~/.gemini/antigravity/brain/index.db"),
            os.path.expanduser("~/.gemini/antigravity/antigravity.db"),
        ]
        if conversation_id:
            candidate_paths.append(
                os.path.expanduser(f"~/.gemini/antigravity/conversations/{conversation_id}.db")
            )

        for db_path in candidate_paths:
            if not os.path.exists(db_path):
                continue

            # Requirement 1 & 2: Read-only URI and with sqlite3.connect(...) context manager
            with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=1.0) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%trajectory_metadata%'"
                )
                tables = [row[0] for row in cursor.fetchall()]

                for table in tables:
                    cursor.execute(f"PRAGMA table_info({table})")
                    col_info = cursor.fetchall()
                    col_names = [c[1] for c in col_info]

                    blob_col = next(
                        (
                            c[1]
                            for c in col_info
                            if c[2].upper() == "BLOB"
                            or c[1].lower() in ("data", "blob", "metadata", "trajectory_metadata")
                        ),
                        col_names[-1] if col_names else None,
                    )
                    if not blob_col:
                        continue

                    # Query the table containing trajectory_metadata for conversation_id
                    rows = []
                    if "conversation_id" in col_names and conversation_id:
                        cursor.execute(
                            f"SELECT {blob_col} FROM {table} WHERE conversation_id = ?",
                            (conversation_id,),
                        )
                        rows = cursor.fetchall()
                    elif "id" in col_names and conversation_id:
                        cursor.execute(
                            f"SELECT {blob_col} FROM {table} WHERE id = ?",
                            (conversation_id,),
                        )
                        rows = cursor.fetchall()
                        if not rows and f"/{conversation_id}.db" in db_path:
                            cursor.execute(f"SELECT {blob_col} FROM {table} WHERE id = 'main'")
                            rows = cursor.fetchall()
                    elif "id" in col_names:
                        cursor.execute(f"SELECT {blob_col} FROM {table} WHERE id = 'main'")
                        rows = cursor.fetchall()
                    else:
                        cursor.execute(f"SELECT {blob_col} FROM {table} LIMIT 1")
                        rows = cursor.fetchall()

                    for row in rows:
                        blob = row[0]
                        if blob and isinstance(blob, (bytes, bytearray)):
                            return has_protobuf_field_5(blob)

        return fallback
    except Exception:
        # Requirement 3: Defensive Fallback
        return fallback


def main():
    try:
        raw_payload = sys.stdin.read()
        if not raw_payload or not raw_payload.strip():
            print(json.dumps({"decision": "allow"}))
            return

        data = json.loads(raw_payload)

        # Allow subagents to execute freely
        conv_id = data.get("conversationId", "")
        model_name = data.get("modelName", "")
        transcript_path = data.get("transcriptPath", "")
        if is_subagent(conv_id, model_name, transcript_path):
            print(json.dumps({"decision": "allow"}))
            return

        # Allow Primary Agent to write artifacts (implementation_plan.md, task.md, etc.)
        tool_call = data.get("toolCall", {})
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile", "") or args.get("target_file", "") or args.get("path", "")
        artifact_dir = data.get("artifactDirectoryPath", "")

        if is_artifact_path(target_file, artifact_dir):
            print(json.dumps({"decision": "allow"}))
            return

        # Check if this is an MCP tool call
        tool_name = tool_call.get("name", "")
        if tool_name == "call_mcp_tool":
            mcp_tool = args.get("ToolName", "").lower()
            # Discover MCP write tools dynamically from schema directories
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
