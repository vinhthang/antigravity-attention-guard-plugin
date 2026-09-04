#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import is_subagent, get_cache_dir

MAX_STOP_REJECTIONS = 3
MAX_INJECTION_BYTES = 16384


def find_rules(workspace_paths):
    """Discover applicable rule files only (no skills).

    Loads: plugin core rules, workspace rules, global always-on rules.
    Excludes: skills (they use progressive disclosure and shouldn't be bulk-injected).
    """
    plugin_rules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules"))
    rules = []

    # 1. Plugin's own rules
    if os.path.exists(plugin_rules_dir):
        for f in sorted(os.listdir(plugin_rules_dir)):
            if f.endswith(".md"):
                rules.append(os.path.join(plugin_rules_dir, f))

    # 2. Workspace-level instructions
    for wp in workspace_paths:
        if not wp or not os.path.exists(wp):
            continue
        for name in ["GEMINI.md", "AGENTS.md"]:
            path = os.path.join(wp, name)
            if os.path.exists(path):
                rules.append(path)
        agents_dir = os.path.join(wp, ".agents", "rules")
        if os.path.exists(agents_dir):
            for root, _, files in os.walk(agents_dir):
                for f in sorted(files):
                    if f.endswith(".md"):
                        rules.append(os.path.join(root, f))

    # 3. Global rules (NOT skills — skills use progressive disclosure)
    global_rules_dir = os.path.expanduser("~/.gemini/config/rules")
    if os.path.exists(global_rules_dir):
        for root, _, files in os.walk(global_rules_dir):
            for f in sorted(files):
                if f.endswith(".md"):
                    rules.append(os.path.join(root, f))

    # Deduplicate while preserving order
    seen = set()
    return [r for r in rules if not (r in seen or seen.add(r))]


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

    lower_content = last_model_content.lower()
    has_summary = "summary of skills used:" in lower_content or "no skills used" in lower_content

    if not has_summary:
        rejection_count = get_rejection_count(tracker)
        if rejection_count >= MAX_STOP_REJECTIONS:
            reset_rejection_count(tracker)
            print(json.dumps({"decision": "allow"}))
            return

        increment_rejection_count(tracker)

        workspace_paths = payload.get("workspacePaths", [])
        rules_to_read = find_rules(workspace_paths)

        rule_contents = []
        for rule_path in rules_to_read:
            try:
                with open(rule_path, "r") as rf:
                    content = rf.read()
                rule_contents.append(f"=== {os.path.basename(rule_path)} ===\n{content}")
            except Exception:
                rule_contents.append(f"=== {os.path.basename(rule_path)} === (could not read)")

        base_msg = (
            "Your response is missing 'Summary of skills used:'. "
            "(If you only answered a conversational question, you may include 'No skills used' instead.)\n"
            "The following rules have been reintroduced into your context. "
            "Review them and include the summary in your response.\n\n"
        )
        
        injected_text = base_msg
        current_bytes = len(injected_text.encode("utf-8"))
        
        for content in rule_contents:
            rule_bytes = len((content + "\n\n").encode("utf-8"))
            if current_bytes + rule_bytes > MAX_INJECTION_BYTES:
                injected_text += "\n\n[... remaining rules truncated to prevent context overflow ...]"
                break
            injected_text += content + "\n\n"

        print(json.dumps({"decision": "continue", "reason": injected_text}))
    else:
        reset_rejection_count(tracker)
        print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
