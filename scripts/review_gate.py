#!/usr/bin/env python3
import os
import json
from typing import Tuple, Optional

GATE_ERR_MISSING = "Plan Review Gate: review.json missing. Phase 2 execution blocked until live WorkBuddy review completes with 0 P0/P1 issues."
GATE_ERR_EMPTY = "Plan Review Gate: review.json is empty (0 bytes)."
GATE_ERR_MALFORMED = "Plan Review Gate: review.json contains malformed or unparseable JSON syntax."
GATE_ERR_MISSING_KEYS = "Plan Review Gate: review.json is missing required envelope keys (engine, session_id, issues)."
GATE_ERR_INVALID_SESSION = "Plan Review Gate: review.json contains invalid session_id format for engine."
GATE_ERR_INVALID_ISSUES = "Plan Review Gate: review.json contains invalid issues structure (must be list of objects)."
GATE_ERR_INVALID_SEVERITY = "Plan Review Gate: review.json contains invalid issue severity or description format."
GATE_ERR_BLOCKING = "Plan Review Gate: review.json contains unresolved blocking issues (P0/P1)."

def validate_review_gate(workspace_root: str, artifact_path: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """Validate review gate envelope against Dalio Step 4 gating rules."""
    target_path = artifact_path
    if not target_path:
        target_path = os.path.join(workspace_root, "review.json")
    
    if not os.path.isfile(target_path):
        return False, GATE_ERR_MISSING
    
    if os.path.getsize(target_path) == 0:
        return False, GATE_ERR_EMPTY
    
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False, GATE_ERR_MALFORMED
    
    if not isinstance(data, dict):
        return False, GATE_ERR_MALFORMED
    
    for key in ("engine", "session_id", "issues"):
        if key not in data:
            return False, GATE_ERR_MISSING_KEYS
    
    engine = data.get("engine")
    session_id = data.get("session_id")
    if not isinstance(engine, str) or not isinstance(session_id, str):
        return False, GATE_ERR_MISSING_KEYS
    
    if engine == "workbuddy":
        if not session_id.startswith("workbuddy:") or len(session_id) <= 10:
            return False, GATE_ERR_INVALID_SESSION
    elif engine == "codex":
        if session_id.startswith("workbuddy:"):
            return False, GATE_ERR_INVALID_SESSION
    else:
        return False, GATE_ERR_MISSING_KEYS
    
    issues = data.get("issues")
    if not isinstance(issues, list):
        return False, GATE_ERR_INVALID_ISSUES
    
    blocking = []
    for item in issues:
        if not isinstance(item, dict):
            return False, GATE_ERR_INVALID_ISSUES
        sev = item.get("severity")
        desc = item.get("description")
        if sev not in ("P0", "P1", "P2"):
            return False, GATE_ERR_INVALID_SEVERITY
        if not isinstance(desc, str) or not desc.strip():
            return False, GATE_ERR_INVALID_SEVERITY
        if sev in ("P0", "P1"):
            blocking.append(item)
            
    if blocking:
        return False, GATE_ERR_BLOCKING
        
    return True, None
