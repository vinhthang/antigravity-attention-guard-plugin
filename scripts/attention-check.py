#!/usr/bin/env python3
import sys, json, os, time, argparse

def find_rules(workspace_paths, plugin_rules_path):
    rules = [plugin_rules_path]
    for wp in workspace_paths:
        if not wp or not os.path.exists(wp): continue
        for r in [os.path.join(wp, "GEMINI.md"), os.path.join(wp, "AGENTS.md")]:
            if os.path.exists(r): rules.append(r)
        agents_dir = os.path.join(wp, ".agents", "rules")
        if os.path.exists(agents_dir):
            for root, _, files in os.walk(agents_dir):
                for f in files:
                    if f.endswith(".md"): rules.append(os.path.join(root, f))
    
    global_rules_dir = os.path.expanduser("~/.gemini/config/rules")
    if os.path.exists(global_rules_dir):
        for root, _, files in os.walk(global_rules_dir):
            for f in files:
                if f.endswith(".md"): rules.append(os.path.join(root, f))
    
    seen = set()
    return [r for r in rules if not (r in seen or seen.add(r))]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args, _ = parser.parse_known_args()

    try:
        payload = json.load(sys.stdin)
    except:
        print(json.dumps({})); return

    if not payload.get("fullyIdle", True):
        print(json.dumps({})); return

    transcript_path = payload.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        print(json.dumps({})); return

    last_model_content = None
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if not line.strip(): continue
            try:
                record = json.loads(line)
                if record.get("source") == "MODEL" and record.get("type") == "PLANNER_RESPONSE":
                    last_model_content = record.get("content", "")
            except: pass

    if last_model_content is None:
        print(json.dumps({})); return

    is_subagent = "flash" in payload.get("modelName", "").lower()
    has_delegated = False
    with open(transcript_path, "r", encoding="utf-8") as f:
        for line in f:
            if '"invoke_subagent"' in line:
                has_delegated = True; break

    conv_id = payload.get("conversationId", "unknown")
    tracker = f"/tmp/agy_start_{conv_id}"
    elapsed = 0
    if os.path.exists(tracker):
        try:
            with open(tracker, "r") as f: elapsed = time.time() - float(f.read().strip())
        except: pass

    if is_subagent or has_delegated or elapsed <= args.timeout:
        print(json.dumps({})); return

    if "Summary of skills used:" not in last_model_content:
        plugin_rules_path = os.path.abspath(os.path.join(os.getcwd(), "rules", "AGENTS.md"))
        workspace_paths = payload.get("workspacePaths", [])
        rules_to_read = find_rules(workspace_paths, plugin_rules_path)
        rules_list = "\n".join([f"{i+1}. {r}" for i, r in enumerate(rules_to_read)])
        
        reason = (
            "ATTENTION DILUTION DETECTED! You forgot to report the 'Summary of skills used:'. "
            "You MUST stop, and before writing code again, you must reset your context by using the view_file tool to read the following active rules:\n"
            f"{rules_list}\n"
            "Correct your mistake."
        )
        print(json.dumps({"decision": "continue", "reason": reason}))
    else:
        print(json.dumps({}))

if __name__ == "__main__":
    main()
