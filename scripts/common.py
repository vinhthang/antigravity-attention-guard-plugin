import os
import json
import re
import time
from ledger import Ledger

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def get_turn_state(transcript_path):
    turn_id = 0
    lines_count = 0
    if not transcript_path or not os.path.exists(transcript_path):
        return turn_id, lines_count
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                lines_count += 1
                try:
                    step = json.loads(line)
                    if str(step.get("source", "")).startswith("USER"):
                        turn_id += 1
                except Exception:
                    pass
    except Exception:
        pass
    return turn_id, lines_count

def is_subagent(data):
    """Determine if the current agent is a subagent using the Ledger."""
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return False, False, 0, None, None

    conv_id = data.get("conversationId", "unknown")
    turn_id, _ = get_turn_state(transcript_path)
    
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            content = f.read(8192)

        matches = re.finditer(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', content)
        ledger = Ledger()
        
        for match in matches:
            token = match.group(1)
            
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?", (f'%"{token}"%',))
                row = cursor.fetchone()
                if row:
                    payload_data = json.loads(row[0])
                    may_delegate = payload_data.get("may_delegate", False)
                    remaining_depth = payload_data.get("remaining_depth", 0)
                    parent_conv_id = payload_data.get("parent_conv_id", "unknown")
                    parent_turn_id = payload_data.get("parent_turn_id", "unknown")
                    
                    if ledger.claim_token(token):
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "WORK_CLAIMED")
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "RUNNING")
                        
                    return True, may_delegate, remaining_depth, parent_conv_id, parent_turn_id
                    
    except Exception:
        pass

    return False, False, 0, None, None
