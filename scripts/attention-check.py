#!/usr/bin/env python3
import sys, json, os, time, argparse

MAX_STOP_REJECTIONS = 3


def get_cache_dir():
    cache_dir = os.environ.get("AGY_CACHE_DIR") or os.path.expanduser("~/.gemini/antigravity/cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def is_subagent(data):
    """Detect if the current agent is a subagent via modelName or transcript marker."""
    model_name = data.get("modelName", "").lower()
    if "flash" in model_name:
        return True

    transcript_path = data.get("transcriptPath", "")
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "rb") as f:
                chunk = f.read(8192)
            if b"[ANTIGRAVITY_SUBAGENT:" in chunk:
                return True
        except Exception:
            pass

    return False


def find_rules(workspace_paths):
    """Discover all instruction files: plugin rules, project rules, global rules, and skills."""
    plugin_rules_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "rules"))
    rules = []

    # 1. Plugin's own rules
    if os.path.exists(plugin_rules_dir):
        for f in sorted(os.listdir(plugin_rules_dir)):
            if f.endswith(".md"):
                rules.append(os.path.join(plugin_rules_dir, f))

    # 2. Workspace-level instructions (GEMINI.md, AGENTS.md, .agents/rules/)
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

    # 3. Global rules
    global_rules_dir = os.path.expanduser("~/.gemini/config/rules")
    if os.path.exists(global_rules_dir):
        for root, _, files in os.walk(global_rules_dir):
            for f in sorted(files):
                if f.endswith(".md"):
                    rules.append(os.path.join(root, f))

    # 4. Global skills
    global_skills_dir = os.path.expanduser("~/.gemini/config/skills")
    if os.path.exists(global_skills_dir):
        for skill_name in sorted(os.listdir(global_skills_dir)):
            skill_md = os.path.join(global_skills_dir, skill_name, "SKILL.md")
            if os.path.exists(skill_md):
                rules.append(skill_md)

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
            # Check remainder
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
    """Read the stop rejection counter."""
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args, _ = parser.parse_known_args()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return

    # Skip if agent is waiting for subagents
    if not payload.get("fullyIdle", True):
        print(json.dumps({}))
        return

    # Skip for subagents
    if is_subagent(payload):
        print(json.dumps({}))
        return

    # Check elapsed time
    conv_id = payload.get("conversationId", "unknown")
    tracker = os.path.join(get_cache_dir(), f"agy_start_{conv_id}")
    elapsed = 0
    if os.path.exists(tracker):
        try:
            with open(tracker, "r") as f:
                elapsed = time.time() - float(f.read().strip())
        except Exception:
            pass

    if elapsed <= args.timeout:
        reset_rejection_count(tracker)
        print(json.dumps({}))
        return

    # Get last model response efficiently (reverse scan)
    transcript_path = payload.get("transcriptPath", "")
    last_model_content = get_last_model_content(transcript_path)

    if last_model_content is None:
        print(json.dumps({}))
        return

    if "summary of skills used:" not in last_model_content.lower():
        # Prevent infinite rejection loop
        rejection_count = get_rejection_count(tracker)
        if rejection_count >= MAX_STOP_REJECTIONS:
            reset_rejection_count(tracker)
            print(json.dumps({}))
            return

        increment_rejection_count(tracker)

        workspace_paths = payload.get("workspacePaths", [])
        rules_to_read = find_rules(workspace_paths)

        # Read all rule file contents directly
        rule_contents = []
        for rule_path in rules_to_read:
            try:
                with open(rule_path, "r") as rf:
                    content = rf.read()
                rule_contents.append(f"=== {os.path.basename(rule_path)} ===\n{content}")
            except Exception:
                rule_contents.append(f"=== {os.path.basename(rule_path)} === (could not read)")

        injected_text = (
            "ATTENTION DILUTION DETECTED! You forgot to report the 'Summary of skills used:'. "
            "Your context has been refreshed with all active rules below. "
            "Re-read them carefully and correct your response.\n\n"
            + "\n\n".join(rule_contents)
        )
        print(json.dumps({"decision": "continue", "injectSteps": [{"ephemeralMessage": injected_text}]}))
    else:
        reset_rejection_count(tracker)
        print(json.dumps({}))


if __name__ == "__main__":
    main()
