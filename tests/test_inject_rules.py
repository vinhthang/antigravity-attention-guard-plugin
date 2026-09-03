#!/usr/bin/env python3
import json
import os
import re
import subprocess
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "inject-rules.py")


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout)


class TestInjectRules:
    def test_injects_marker_and_rules(self):
        payload = {
            "conversationId": "parent-conv-1234",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {
                            "TypeName": "research",
                            "Prompt": "Please research the codebase."
                        }
                    ]
                }
            }
        }
        result = run_hook(payload)
        assert result["decision"] == "allow"
        assert "overwrite" in result
        subagents = result["overwrite"]["Subagents"]
        assert len(subagents) == 1
        prompt = subagents[0]["Prompt"]
        assert "Please research the codebase." in prompt
        assert "--- INJECTED RULES ---" in prompt
        assert re.search(r'\[ANTIGRAVITY_SUBAGENT:parent-conv-1234:\d+\]', prompt) is not None

    def test_injects_marker_for_multiple_subagents(self):
        payload = {
            "conversationId": "parent-multi-5678",
            "toolCall": {
                "name": "invoke_subagent",
                "args": {
                    "Subagents": [
                        {"TypeName": "sub1", "Prompt": "Task 1"},
                        {"TypeName": "sub2", "Prompt": "Task 2"}
                    ]
                }
            }
        }
        result = run_hook(payload)
        assert result["decision"] == "allow"
        subagents = result["overwrite"]["Subagents"]
        assert len(subagents) == 2
        for sa in subagents:
            assert re.search(r'\[ANTIGRAVITY_SUBAGENT:parent-multi-5678:\d+\]', sa["Prompt"]) is not None

    def test_non_subagent_tool_passthrough(self):
        payload = {
            "conversationId": "parent-conv-999",
            "toolCall": {
                "name": "run_command",
                "args": {"CommandLine": "ls"}
            }
        }
        result = run_hook(payload)
        assert result["decision"] == "allow"
        assert "overwrite" not in result

    def test_empty_payload(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="",
            capture_output=True, text=True, timeout=5
        )
        output = json.loads(result.stdout)
        assert output["decision"] == "allow"

def test_unique_sequence():
    pass
