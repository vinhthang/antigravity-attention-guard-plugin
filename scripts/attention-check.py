#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import is_subagent, get_cache_dir

MAX_STOP_REJECTIONS = 2

def has_delegated(transcript_path):
    if not transcript_path or not os.path.exists(transcript_path):
        return False
    try:
        found_delegation = False
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    step = json.loads(line)
                    if str(step.get("source", "")).startswith("USER"):
                        found_delegation = False
                    if step.get("source") == "MODEL" and "tool_calls" in step:
                        for tc in step["tool_calls"]:
                            if tc.get("name") in ["invoke_subagent", "manage_subagents"]:
                                found_delegation = True
                except json.JSONDecodeError:
                    pass
        return found_delegation
    except Exception:
        pass
    return False

def get_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    if os.path.exists(count_file):
        try:
            with open(count_file, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return 0

def increment_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    count = get_rejection_count(tracker) + 1
    with open(count_file, "w") as f:
        f.write(str(count))
    return count

def reset_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    if os.path.exists(count_file):
        os.remove(count_file)

def main(argv=None, stdin=None, stdout=None):
    if argv is None:
        argv = sys.argv
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    def emit(data):
        stdout.write(json.dumps(data) + "\n")

    try:
        payload = json.loads(stdin.read())
    except Exception:
        emit({"decision": "allow"})
        return

    if not payload.get("fullyIdle", True):
        emit({"decision": "allow"})
        return

    is_sub, _ = is_subagent(payload)
    if is_sub:
        emit({"decision": "allow"})
        return

    conv_id = payload.get("conversationId", "unknown")
    tracker = os.path.join(get_cache_dir(), f"reject_count_{conv_id}")
    transcript_path = payload.get("transcriptPath", "")

    if has_delegated(transcript_path):
        reset_rejection_count(tracker)
        emit({"decision": "allow"})
        return

    rejection_count = get_rejection_count(tracker)
    if rejection_count >= MAX_STOP_REJECTIONS:
        reset_rejection_count(tracker)
        emit({"decision": "allow"})
        return

    rejection_count = increment_rejection_count(tracker)
    injected_text = f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"
    
    emit({"decision": "continue", "reason": injected_text})

if __name__ == "__main__":
    main()
