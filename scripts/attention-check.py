#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import is_subagent, get_cache_dir, get_turn_state

MAX_STOP_REJECTIONS = 2

def has_valid_handoff_after(transcript_path, start_line):
    if not transcript_path or not os.path.exists(transcript_path):
        return False
    try:
        valid_invokes = 0
        with open(transcript_path, "r", encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                try:
                    step = json.loads(line)
                    # Check for MODEL tool call
                    if step.get("source") == "MODEL" and "tool_calls" in step:
                        for tc in step["tool_calls"]:
                            name = tc.get("name", "")
                            args_str = json.dumps(tc.get("args", {}))
                            if name in ["invoke_subagent", "default_api:invoke_subagent"]:
                                # ignore dummy tasks
                                if "date" not in args_str.lower() and "dummy" not in args_str.lower():
                                    valid_invokes += 1
                    # Check for TOOL response indicating failure
                    if step.get("source") == "TOOL" or step.get("type") == "TOOL_RESPONSE":
                        line_str = line.lower()
                        if "invoke_subagent" in line_str and ("error" in line_str or "deny" in line_str or "denied" in line_str or "fail" in line_str):
                            valid_invokes = max(0, valid_invokes - 1)
                except Exception:
                    pass
        return valid_invokes > 0
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
        try:
            os.remove(count_file)
        except: pass
    if os.path.exists(tracker + ".json"):
        try:
            os.remove(tracker + ".json")
        except: pass

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

    is_sub, _, _ = is_subagent(payload)
    if is_sub:
        emit({"decision": "allow"})
        return

    conv_id = payload.get("conversationId", "unknown")
    transcript_path = payload.get("transcriptPath", "")
    turn_id, _ = get_turn_state(transcript_path)
    
    tracker = os.path.join(get_cache_dir(), f"violation_{conv_id}_{turn_id}")
    marker_path = tracker + ".json"
    
    if not os.path.exists(marker_path):
        emit({"decision": "allow"})
        return
        
    try:
        with open(marker_path, "r") as f:
            marker = json.load(f)
        start_line = marker.get("transcript_lines", 0)
    except Exception:
        emit({"decision": "allow"})
        return

    if has_valid_handoff_after(transcript_path, start_line):
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
