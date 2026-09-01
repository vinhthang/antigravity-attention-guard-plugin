#!/usr/bin/env python3
import subprocess
import json
import os
import tempfile
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "output-guard.py")


def run_hook(payload):
    result = subprocess.run(
        ["python3", SCRIPT],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10
    )
    return json.loads(result.stdout)


class TestOutputGuard:
    def test_no_warning_for_small_output(self):
        transcript = os.path.join(tempfile.gettempdir(), "test_transcript_small.jsonl")
        with open(transcript, "w") as f:
            f.write(json.dumps({"source": "MODEL", "type": "GENERIC", "content": "small output"}) + "\n")
        result = run_hook({"transcriptPath": transcript})
        assert result == {}
        os.remove(transcript)

    def test_warning_for_large_output(self):
        transcript = os.path.join(tempfile.gettempdir(), "test_transcript_large.jsonl")
        large_content = "x" * 25000
        with open(transcript, "w") as f:
            f.write(json.dumps({"source": "MODEL", "type": "GENERIC", "content": large_content}) + "\n")
        result = run_hook({"transcriptPath": transcript})
        assert "injectSteps" in result
        assert "OUTPUT SIZE WARNING" in result["injectSteps"][0]["ephemeralMessage"]
        os.remove(transcript)

    def test_no_transcript(self):
        result = run_hook({"transcriptPath": "/nonexistent/path"})
        assert result == {}

    def test_empty_payload(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            input="",
            capture_output=True, text=True, timeout=5
        )
        assert json.loads(result.stdout) == {}
