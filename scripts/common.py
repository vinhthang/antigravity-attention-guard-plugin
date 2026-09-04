import os
import json
import re

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def is_subagent(data):
    """Determine if the current agent is a subagent using Issued Tokens.
    Reads only the first 8192 bytes of the transcript to find the token.
    Validates the token against the issued token cache.
    """
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return False

    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read(8192)

        match = re.search(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', content)
        if match:
            token = match.group(1)
            token_file = os.path.join(get_cache_dir(), f"agy_issued_token_{token}")
            if os.path.exists(token_file):
                # Simple GC: clean up old tokens in the cache dir while we're here
                try:
                    import time
                    now = time.time()
                    for f in os.listdir(get_cache_dir()):
                        if f.startswith("agy_issued_token_"):
                            f_path = os.path.join(get_cache_dir(), f)
                            if now - os.path.getmtime(f_path) > 86400: # 24 hours
                                os.remove(f_path)
                except Exception:
                    pass
                return True
    except Exception:
        pass

    return False
