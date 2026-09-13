import sys
import os
import json
import re
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
                if line.strip():
                    lines_count += 1
                    try:
                        step = json.loads(line)
                        if str(step.get("source", "")).startswith("USER") and step.get("type") == "USER_INPUT":
                            turn_id = step.get("step_index", turn_id)
                    except Exception as exc:
                        sys.stderr.write(f"Warning: {exc}\n")
    except Exception as exc:
        sys.stderr.write(f"Warning: {exc}\n")
    return turn_id, lines_count

def is_subagent(data):
    transcript_path = data.get("transcriptPath", "")
    if not transcript_path or not os.path.exists(transcript_path):
        return False, False, 0, None, None

    conv_id = data.get("conversationId", "unknown")
    turn_id, _ = get_turn_state(transcript_path)
    
    try:
        tokens = []
        token_pattern = re.compile(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]')
        with open(transcript_path, "r", encoding="utf-8") as f:
            for line in f:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    step = json.loads(line_str)
                    if step.get("type") == "USER_INPUT":
                        content = step.get("content", "")
                        for match in token_pattern.finditer(content):
                            tok = match.group(1)
                            if tok not in tokens:
                                tokens.append(tok)
                        break
                except Exception:
                    break

        ledger = Ledger()
        for token in tokens:
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?", (f'%"{token}"%',))
                row = cursor.fetchone()
                if row:
                    payload_data = json.loads(row[0])
                    may_delegate = payload_data.get("may_delegate", False)
                    remaining_depth = payload_data.get("remaining_depth", 0)
                    parent_conv_id = payload_data.get("parent_conv_id", "unknown")
                    parent_turn_id = payload_data.get("parent_turn_id", "unknown")

                    if conv_id == parent_conv_id:
                        continue

                    if ledger.claim_token(token, conv_id):
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "WORK_CLAIMED")
                        ledger.insert_event(conv_id, str(turn_id), "init", "0", token, "RUNNING")
                        return True, may_delegate, remaining_depth, parent_conv_id, parent_turn_id


    except Exception as exc:
        sys.stderr.write(f"Error in is_subagent: {exc}\n")

    return False, False, 0, None, None
