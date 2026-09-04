import os
import json

def get_cache_dir():
    base = os.environ.get("AGY_APP_DATA_DIR") or os.path.join(os.path.expanduser("~"), ".gemini", "antigravity")
    cache = os.path.join(base, "cache")
    os.makedirs(cache, exist_ok=True)
    return cache

def is_subagent(data):
    """Determine if the current agent is a subagent using 3-layer detection.
    
    Layer 1: ConversationId tracking — if this ID is recorded as a primary agent
             AND has no transcript marker, return False.
    Layer 2: Transcript marker scan — raw byte scan for [ANTIGRAVITY_SUBAGENT: marker.
    Layer 3: Flash model heuristic — if no transcript is available, check modelName.
    
    Multi-level delegation: If an agent has BOTH a primary cache file (it spawned
    subagents) AND a transcript marker (it WAS spawned as a subagent), the marker
    takes precedence — it's a middle-tier agent and should be treated as a subagent.
    """
    current_id = data.get("conversationId", "")
    cache_dir = get_cache_dir()
    
    # Check transcript marker first (strongest signal for subagent identity)
    transcript_path = data.get("transcriptPath", "")
    has_marker = False
    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                content = f.read(32768)
            has_marker = "[ANTIGRAVITY_SUBAGENT:" in content
        except Exception:
            pass
    
    # Layer 1: ConversationId is KNOWN to be a primary agent
    if current_id:
        primary_file = os.path.join(cache_dir, f"agy_primary_{current_id}")
        if os.path.exists(primary_file):
            if has_marker:
                return True   # Middle-tier: spawned AS subagent → treat as subagent
            return False      # Pure primary: no marker → block
    
    # Layer 2: Has marker → subagent
    if has_marker:
        return True
    
    # Transcript exists but no marker → not a subagent
    if transcript_path and os.path.exists(transcript_path):
        return False
    
    # Layer 3: Flash model heuristic (no transcript available)
    return "flash" in data.get("modelName", "").lower()
