#!/usr/bin/env python3
import sys
import os
import io
import importlib.util
import json
import pytest

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

        cache_dir = os.path.join(str(tmp_path), "cache")
        token_file = os.path.join(cache_dir, f"agy_issued_token_{token}")
        assert os.path.exists(token_file)

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
