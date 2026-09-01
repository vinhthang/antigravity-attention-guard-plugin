#!/usr/bin/env python3
import subprocess
import json
import os
import time
import tempfile
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "attention-guard.py")


def run_hook(payload, timeout_arg=120):
    result = subprocess.run(
        ["python3", SCRIPT, "--timeout", str(timeout_arg)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=5
    )
    return json.loads(result.stdout)


class TestSubagentSkip:
    def test_subagent_skipped(self):
        result = run_hook({"modelName": "gemini-2.0-flash", "conversationId": "test-1"})
        assert result == {}


class TestTimeoutAlert:
    def test_no_alert_under_timeout(self):
        conv_id = f"test-fresh-{time.time()}"
        tracker = os.path.join(tempfile.gettempdir(), f"agy_start_{conv_id}")
        # Create a fresh tracker (just started)
        with open(tracker, "w") as f:
            f.write(str(time.time()))
        result = run_hook({"modelName": "claude-opus-4.6", "conversationId": conv_id, "artifactDirectoryPath": "/tmp/test"}, timeout_arg=120)
        assert result == {}
        os.remove(tracker)

    def test_alert_over_timeout(self):
        conv_id = f"test-old-{time.time()}"
        tracker = os.path.join(tempfile.gettempdir(), f"agy_start_{conv_id}")
        # Create a stale tracker (started 200s ago)
        with open(tracker, "w") as f:
            f.write(str(time.time() - 200))
        result = run_hook({"modelName": "claude-opus-4.6", "conversationId": conv_id, "artifactDirectoryPath": "/tmp/nonexistent"}, timeout_arg=120)
        assert "injectSteps" in result
        assert "ATTENTION" in result["injectSteps"][0]["ephemeralMessage"]
        os.remove(tracker)


class TestEdgeCases:
    def test_empty_stdin(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="",
            capture_output=True, text=True, timeout=5
        )
        assert json.loads(result.stdout) == {}
