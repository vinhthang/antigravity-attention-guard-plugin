#!/usr/bin/env python3
import sys
import os
import io
import importlib.util
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../scripts')))
from ledger import Ledger

spec = importlib.util.spec_from_file_location(
    "inject_rules",
    os.path.join(os.path.dirname(__file__), "../scripts/inject-rules.py")
)
inject_mod = importlib.util.module_from_spec(spec)
sys.modules["inject_rules"] = inject_mod
spec.loader.exec_module(inject_mod)

@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)

def run_hook(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    inject_mod.main(argv=["inject-rules.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

class TestRuleInjection:
    def test_injects_rules_into_subagent_prompt(self):
        result = run_hook({
            "conversationId": "parent-123",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [{"Prompt": "Do something", "Role": "Worker"}]
                }
            }
        })
        assert result["decision"] == "allow"
        assert "overwrite" in result
        subagents = result["overwrite"]["Subagents"]
        assert len(subagents) == 1
        assert "[ANTIGRAVITY_TOKEN:" in subagents[0]["Prompt"]
        assert "INJECTED RULES" in subagents[0]["Prompt"]

    def test_issues_tokens(self, tmp_path):
        """invoke_subagent should issue tokens for subagents."""
        result = run_hook({
            "conversationId": "primary-abc-123",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [{"Prompt": "Work"}]
                }
            }
        })
        assert result["decision"] == "allow"
        subagents = result["overwrite"]["Subagents"]

        import re
        match = re.search(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', subagents[0]["Prompt"])
        assert match
        token = match.group(1)

        import ledger
        importlib.reload(ledger)
        l = ledger.Ledger()
        with l._get_connection() as conn:
            cursor = conn.execute("SELECT * FROM tokens WHERE token_id = ?", (token,))
            assert cursor.fetchone() is not None
            
            cursor = conn.execute("SELECT * FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?", (f'%"{token}"%',))
            assert cursor.fetchone() is not None

    def test_unique_tokens_in_batch(self):
        result = run_hook({
            "conversationId": "parent-456",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"Prompt": "Task 1"},
                        {"Prompt": "Task 2"},
                        {"Prompt": "Task 3"}
                    ]
                }
            }
        })
        subagents = result["overwrite"]["Subagents"]
        # Extract tokens
        tokens = []
        for sa in subagents:
            import re
            match = re.search(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', sa["Prompt"])
            assert match, f"Token not found in prompt: {sa['Prompt'][-100:]}"
            tokens.append(match.group(1))
        # All tokens should be unique
        assert len(set(tokens)) == 3, f"Tokens should be unique: {tokens}"

    def test_non_subagent_tool_passes_through(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result

def test_coordinator_creates_leaf_worker(tmp_path):
    import os, json, re
    import ledger
    importlib.reload(ledger)
    l = ledger.Ledger()
    
    parent_token = "a1b2c3d4-1234"
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (parent_token,))
    payload_data = {"token": parent_token, "may_delegate": True, "remaining_depth": 1, "parent_conv_id": "root", "parent_turn_id": "1"}
    l.insert_event("root", "1", "PreToolUse", "0", parent_token, "WORK_PREPARED", json.dumps(payload_data))

    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do the task\\n\\n[ANTIGRAVITY_TOKEN:{parent_token}]"}}\n'
    )

    result = run_hook({
        "conversationId": "coord-conv",
        "transcriptPath": str(transcript),
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"Prompt": "Do work", "TypeName": "DeepCoder"}]
            }
        }
    })
    
    subagents = result["overwrite"]["Subagents"]
    match = re.search(r'\[ANTIGRAVITY_TOKEN:([a-f0-9\-]+)\]', subagents[0]["Prompt"])
    child_token = match.group(1)

    with l._get_connection() as conn:
        cursor = conn.execute("SELECT payload FROM events WHERE type = 'WORK_PREPARED' AND payload LIKE ?", (f'%"{child_token}"%',))
        row = cursor.fetchone()
        assert row is not None
        child_data = json.loads(row[0])
    
    assert child_data["may_delegate"] is False
    assert child_data["remaining_depth"] == 0
