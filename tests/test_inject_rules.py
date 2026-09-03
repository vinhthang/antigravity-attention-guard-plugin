#!/usr/bin/env python3
import subprocess
import json
import os
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "inject-rules.py")


@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5,
        env=os.environ.copy()
    )
    return json.loads(result.stdout)


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
        assert "[ANTIGRAVITY_SUBAGENT:parent-123:" in subagents[0]["Prompt"]
        assert "INJECTED RULES" in subagents[0]["Prompt"]

    def test_records_primary_agent_id(self, tmp_path):
        """invoke_subagent should record the parent's conversationId as primary."""
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
        # Check that the primary ID was recorded
        cache_dir = os.path.join(str(tmp_path), "cache")
        primary_file = os.path.join(cache_dir, "agy_primary_primary-abc-123")
        assert os.path.exists(primary_file)

    def test_unique_sequences_in_batch(self):
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
        # Extract markers
        markers = []
        for sa in subagents:
            import re
            match = re.search(r'\[ANTIGRAVITY_SUBAGENT:[^:]+:(\d+)\]', sa["Prompt"])
            assert match, f"Marker not found in prompt: {sa['Prompt'][-100:]}"
            markers.append(int(match.group(1)))
        # All markers should be unique and sequential
        assert len(set(markers)) == 3, f"Markers should be unique: {markers}"
        assert markers[1] == markers[0] + 1
        assert markers[2] == markers[1] + 1

    def test_non_subagent_tool_passes_through(self):
        result = run_hook({
            "toolCall": {"name": "run_command", "args": {}}
        })
        assert result["decision"] == "allow"
        assert "overwrite" not in result
