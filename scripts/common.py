import os
import json

def get_cache_dir():
    cache_dir = os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    return os.environ.get("AGY_APP_DATA_DIR", cache_dir)

def is_subagent(data):
    transcript_path = data.get("transcriptPath")
    if not transcript_path or not os.path.exists(transcript_path):
        model_name = data.get("model", "")
        if not model_name and "model" in data.get("agent", {}):
             model_name = data["agent"]["model"]
        return "flash" in model_name.lower()
        
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                if len(line) > 32768:
                    line = line[:32768]
                if "[ANTIGRAVITY_SUBAGENT:" not in line:
                    continue
                try:
                    record = json.loads(line)
                    source = record.get("source", "")
                    rec_type = record.get("type", "")
                    if source != "USER_EXPLICIT" and rec_type != "USER_INPUT":
                        return True
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
        
    return False
