#!/usr/bin/env python3
import sys, json, os, time, argparse, tempfile


def is_subagent(payload):
    """Detect if the current agent is a subagent using structured metadata."""
    if payload.get("isSubagent", False):
        return True
    if payload.get("parentConversationId"):
        return True
    model_name = payload.get("modelName", "").lower()
    if "flash" in model_name:
        return True
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=int, default=120)
    args, _ = parser.parse_known_args()

    try:
        payload = json.load(sys.stdin)
    except Exception:
        print(json.dumps({}))
        return

    if is_subagent(payload):
        print(json.dumps({}))
        return

    artifact_dir = payload.get("artifactDirectoryPath", "")
    conv_id = payload.get("conversationId", "unknown")

    tracker = os.path.join(tempfile.gettempdir(), f"agy_start_{conv_id}")
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

    if elapsed > args.timeout:
        if plan_path and not os.path.exists(plan_path):
            messages.append(
                f"ATTENTION: Execution time >{args.timeout}s. "
                "You MUST halt and create an implementation_plan.md artifact before proceeding."
            )

    if messages:
        print(json.dumps({"injectSteps": [{"ephemeralMessage": " ".join(messages)}]}))
    else:
        print(json.dumps({}))


if __name__ == "__main__":
    main()
