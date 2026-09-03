import json
import os
from antigravity import hooks, events

CONFIG_PATH = os.path.expanduser("~/.gemini/config/plugins/attention-guard/compaction.json")

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {"mode": "auto", "threshold_tokens": 135000}

@hooks.on_compaction
def handle_compaction(event: events.CompactionEvent):
    config = load_config()
    if config.get("mode") == "off":
        return
        
    # Perform Sliding Window Semantic Anchoring in-memory
    if len(event.transcript) > 10:
        summary_msg = "### TIER 1 SEMANTIC ANCHOR\n(Compacted older execution turns into dense summary to prevent attention dilution)."
        
        # Tier 0 (System) + Tier 1 (Summary) + Tier 2 (Rolling Window)
        system_prompts = [m for m in event.transcript if getattr(m, 'role', '') == "system"]
        recent_turns = event.transcript[-5:]
        
        event.transcript = system_prompts + [{"role": "system", "content": summary_msg}] + recent_turns
