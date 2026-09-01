#!/usr/bin/env python3
import sys
import json
import os


def is_artifact_path(target_file, artifact_dir):
    """Check if target_file is within the artifact (brain/) directory."""
    if not target_file:
        return False
    norm_target = os.path.normpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.normpath(os.path.abspath(artifact_dir))
        if norm_target.startswith(norm_artifact):
            return True
    # Fallback: check if 'brain' is a path component
    return "brain" in norm_target.split(os.sep)


def is_subagent(data):
    """Detect if the current agent is a subagent using structured metadata."""
    if data.get("isSubagent", False):
        return True
    if data.get("parentConversationId"):
        return True
    model_name = data.get("modelName", "").lower()
    if "flash" in model_name:
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

        # Allow Primary Agent to write artifacts (implementation_plan.md, task.md, etc.)
        tool_call = data.get("toolCall", {})
        args = tool_call.get("args", {})
        target_file = args.get("TargetFile", "") or args.get("target_file", "") or args.get("path", "")
        artifact_dir = data.get("artifactDirectoryPath", "")

        if is_artifact_path(target_file, artifact_dir):
            print(json.dumps({"decision": "allow"}))
            return

        # Block Primary Agent from direct code execution and file modifications
        print(json.dumps({
            "decision": "deny",
            "reason": (
                "Attention Dilution Guard: The Primary Agent is restricted to planning "
                "and artifact creation. Direct code modification and shell execution must be "
                "delegated to a subagent (Model: 'flash')."
            )
        }))
    except json.JSONDecodeError:
        print(json.dumps({"decision": "allow"}))
    except Exception:
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
