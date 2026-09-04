import os
import json
import re
import time

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

        conv_id = data.get("conversationId", "unknown")
        matches = re.finditer(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', content)
        now = time.time()
        for match in matches:
            token = match.group(1)
            token_file = os.path.join(get_cache_dir(), f"agy_issued_token_{token}")
            if os.path.exists(token_file):
                try:
                    if now - os.path.getmtime(token_file) > 86400:
                        os.remove(token_file)
                        continue

                    with open(token_file, "r") as f:
                        issuer_id = f.read().strip()
                    if issuer_id != conv_id:
                        return True
                except Exception:
                    pass
    except Exception:
        pass

    return False
