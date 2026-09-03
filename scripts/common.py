import os
import json

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def is_subagent(data):
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return "flash" in data.get("modelName", "").lower()
    
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read(32768)
        for line in content.split("\n"):
            if "[ANTIGRAVITY_SUBAGENT:" not in line:
                continue
            try:
                record = json.loads(line)
                source = record.get("source", "")
                rec_type = record.get("type", "")
                if source in ("SYSTEM", "MODEL", "") and rec_type != "USER_INPUT":
                    return True
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    
    return False
