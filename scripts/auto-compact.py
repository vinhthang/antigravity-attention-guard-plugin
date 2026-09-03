#!/usr/bin/env python3
import sys
import json
import os

def main():
    try:
        raw = sys.stdin.read()
        if not raw.strip():
            print(json.dumps({}))
            return
        payload = json.loads(raw)
    except Exception:
        print(json.dumps({}))
        return

    if not isinstance(payload, dict):
        print(json.dumps({}))
        return

    # Extract transcriptPath
    transcript_path = payload.get("transcriptPath")
    if not transcript_path:
        print(json.dumps({}))
        return

    transcript_path = os.path.expanduser(transcript_path)
    if not os.path.exists(transcript_path):
        print(json.dumps({}))
        return

    # Read compaction.json for mode and threshold_bytes
    config_path = os.path.expanduser("~/.gemini/config/plugins/attention-guard/compaction.json")
    mode = "warning"
    threshold_bytes = 150000

    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                mode = config.get("mode", "warning")
                threshold_bytes = config.get("threshold_bytes", 150000)
        except Exception:
            pass

    # If mode == "off", exit cleanly
    if mode == "off":
        print(json.dumps({}))
        return

    # Check os.path.getsize(transcriptPath)
    try:
        file_size = os.path.getsize(transcript_path)
    except Exception:
        print(json.dumps({}))
        return

    # If size > threshold_bytes
    if file_size > threshold_bytes:
        if mode == "warning":
            msg = "⚠️ WARNING: Attention Dilution risk. Context window is exceptionally large. Consider summarizing your state."
            print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
            return
        elif mode == "auto":
            msg = "🛑 CRITICAL: Context threshold breached. You MUST immediately write a summary of the conversation to your scratch directory and ask the user to start a new session."
            print(json.dumps({"injectSteps": [{"ephemeralMessage": msg}]}))
            return

    print(json.dumps({}))

if __name__ == "__main__":
    main()
