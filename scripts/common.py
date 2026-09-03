import os
import json

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def is_subagent(data):
    """Determine if the current agent is a subagent using 3-layer detection.
    
    Layer 1: ConversationId tracking — if this ID is recorded as a primary agent, return False.
    Layer 2: Transcript marker scan — raw byte scan for [ANTIGRAVITY_SUBAGENT: marker.
             No source/type filtering (the marker appears in USER_INPUT records in real transcripts).
    Layer 3: Flash model heuristic — if no transcript is available, check modelName.
    """
    current_id = data.get("conversationId", "")
    cache_dir = get_cache_dir()
    
    # Layer 1: ConversationId is KNOWN to be a primary agent
    if current_id:
        primary_file = os.path.join(cache_dir, f"agy_primary_{current_id}")
        if os.path.exists(primary_file):
            return False  # Definitively primary
    
    # Layer 2: Transcript marker (raw scan, no source/type filtering)
    transcript_path = data.get("transcriptPath", "")
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                content = f.read(32768)
            if "[ANTIGRAVITY_SUBAGENT:" in content:
                return True  # Has marker -> subagent
        except Exception:
            pass
        # Transcript exists but no marker -> not a subagent
        return False
    
    # Layer 3: Flash model heuristic (no transcript available)
    return "flash" in data.get("modelName", "").lower()
