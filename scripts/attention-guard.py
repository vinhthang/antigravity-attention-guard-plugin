#!/usr/bin/env python3
import sys, json, os, time, argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args, _ = parser.parse_known_args()
    
    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return
        
    artifact_dir = payload.get("artifactDirectoryPath", "")
    conv_id = payload.get("conversationId", "unknown")
    model_name = payload.get("modelName", "").lower()
    is_subagent = "flash" in model_name
    
    tracker = f"/tmp/agy_start_{conv_id}"
    if not os.path.exists(tracker):
        with open(tracker, "w") as f:
            f.write(str(time.time()))
            
    with open(tracker, "r") as f:
        try:
            start_time = float(f.read().strip())
        except Exception:
            start_time = time.time()
            
    elapsed = time.time() - start_time
    plan_path = os.path.join(artifact_dir, "implementation_plan.md") if artifact_dir else ""
    messages = []
    
    if not is_subagent and elapsed > args.timeout:
        if plan_path and not os.path.exists(plan_path):
            messages.append(f"ATTENTION: Execution time >{args.timeout}s. You MUST halt and create an implementation_plan.md artifact before proceeding.")
        messages.append("REMINDER: At the end of your turn, explicitly report the summary of skills used. If you are a subagent, you MUST use the send_message tool to report your final results back to the parent agent before terminating.")
        
    if messages:
        print(json.dumps({"injectSteps": [{"ephemeralMessage": " ".join(messages)}]}))
    else:
        print(json.dumps({}))

if __name__ == "__main__":
    main()
