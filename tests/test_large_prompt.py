import os
import sys
import json
import importlib.util

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from common import is_subagent

def test_large_prompt_token_present(tmp_path):
    os.environ["AGY_APP_DATA_DIR"] = str(tmp_path)
    
    import ledger
    importlib.reload(ledger)
    l = ledger.Ledger()

    token = "1234-abcd"
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
    payload_data = {"token": token, "may_delegate": False, "remaining_depth": 0, "parent_conv_id": "parent", "parent_turn_id": "1"}
    l.insert_event("parent", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload_data))

    large_prompt = "A" * 9000
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "[ANTIGRAVITY_TOKEN:{token}]\\n\\n{large_prompt}"}}\n'
    )

    data = {"transcriptPath": str(transcript), "modelName": "claude-opus-4.6", "conversationId": "child"}
    assert is_subagent(data) == (True, False, 0, "parent", "1")
