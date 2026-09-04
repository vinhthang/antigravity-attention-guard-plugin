#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import is_subagent, get_cache_dir

MAX_STOP_REJECTIONS = 2


def get_last_model_content(transcript_path):
    """Efficiently find the last PLANNER_RESPONSE by reading the file in reverse chunks."""
    if not transcript_path or not os.path.exists(transcript_path):
        return None
    try:
        with open(transcript_path, "rb") as f:
            f.seek(0, os.SEEK_END)
            pos = f.tell()
            remainder = b""
            while pos > 0:
                read_size = min(8192, pos)
                pos -= read_size
                f.seek(pos)
                chunk = f.read(read_size)
                data = chunk + remainder
                lines = data.split(b"\n")
                remainder = lines[0]
                for line in reversed(lines[1:]):
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line.decode("utf-8"))
                        if record.get("source") == "MODEL" and record.get("type") == "PLANNER_RESPONSE":
                            return record.get("content", "")
                    except Exception:
                        continue
            if remainder.strip():
                try:
                    record = json.loads(remainder.decode("utf-8"))
                    if record.get("source") == "MODEL" and record.get("type") == "PLANNER_RESPONSE":
                        return record.get("content", "")
                except Exception:
                    pass
    except Exception:
        return None
    return None


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


def main():
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({"decision": "allow"}))
        return

    # Skip if agent is waiting for subagents
    if not payload.get("fullyIdle", True):
        print(json.dumps({"decision": "allow"}))
        return

    # Skip for subagents
    if is_subagent(payload):
        print(json.dumps({"decision": "allow"}))
        return

    # Get last model response efficiently (reverse scan)
    conv_id = payload.get("conversationId", "unknown")
    tracker = os.path.join(get_cache_dir(), f"reject_count_{conv_id}")
    transcript_path = payload.get("transcriptPath", "")
    last_model_content = get_last_model_content(transcript_path)

    if last_model_content is None:
        print(json.dumps({"decision": "allow"}))
        return

    rejection_count = get_rejection_count(tracker)
    if rejection_count >= MAX_STOP_REJECTIONS:
        reset_rejection_count(tracker)
        print(json.dumps({"decision": "allow"}))
        return

    rejection_count = increment_rejection_count(tracker)

    injected_text = f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"

    print(json.dumps({"decision": "continue", "reason": injected_text}))


if __name__ == "__main__":
    main()
