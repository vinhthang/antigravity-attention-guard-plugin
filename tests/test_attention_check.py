#!/usr/bin/env python3
import subprocess
import json
import os
import time
import tempfile
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "attention-check.py")


@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_CACHE_DIR", str(tmp_path))


def get_cache_dir():
    cache_dir = os.environ.get("AGY_CACHE_DIR") or os.path.expanduser("~/.gemini/antigravity/cache")
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def run_hook(payload, timeout_arg=120):
    env = os.environ.copy()
    result = subprocess.run(
        ["python3", SCRIPT, "--timeout", str(timeout_arg)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env=env
    )
    return json.loads(result.stdout)


def create_transcript(path, entries):
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


class TestSubagentSkip:
    def test_subagent_skipped(self):
        result = run_hook({"fullyIdle": True, "modelName": "gemini-2.0-flash", "conversationId": "chk-1"})
        assert result == {}

    def test_subagent_with_marker_skipped(self, tmp_path):
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"type": "USER_INPUT", "content": "Execute task\\n\\n[ANTIGRAVITY_SUBAGENT:conv-123:456]"}\n')
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": "chk-3",
            "transcriptPath": str(transcript)
        })
        assert result == {}

    def test_not_fully_idle_skipped(self):
        result = run_hook({"fullyIdle": False, "modelName": "claude-opus-4.6", "conversationId": "chk-2"})
        assert result == {}


class TestStopRejectionLimit:
    def test_max_rejections_then_allow(self):
        conv_id = f"chk-limit-{time.time()}"
        tracker = os.path.join(get_cache_dir(), f"agy_start_{conv_id}")
        with open(tracker, "w") as f:
            f.write(str(time.time() - 300))

        transcript = os.path.join(tempfile.gettempdir(), f"transcript_{conv_id}.jsonl")
        create_transcript(transcript, [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I did some work but no summary."}
        ])

        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": transcript,
            "workspacePaths": []
        }

        # First 3 rejections should return "continue"
        for i in range(3):
            result = run_hook(payload, timeout_arg=120)
            assert result.get("decision") == "continue", f"Rejection {i+1} should block"

        # 4th attempt should allow (max rejections reached)
        result = run_hook(payload, timeout_arg=120)
        assert result == {}, "Should allow after max rejections"

        # Cleanup
        os.remove(tracker)
        os.remove(transcript)
        count_file = tracker + "_stop_count"
        if os.path.exists(count_file):
            os.remove(count_file)


class TestSkillsSummaryDetection:
    def test_summary_present_passes(self):
        conv_id = f"chk-pass-{time.time()}"
        tracker = os.path.join(get_cache_dir(), f"agy_start_{conv_id}")
        with open(tracker, "w") as f:
            f.write(str(time.time() - 300))

        transcript = os.path.join(tempfile.gettempdir(), f"transcript_{conv_id}.jsonl")
        create_transcript(transcript, [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done. Summary of skills used: rtk, superpowers."}
        ])

        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": transcript,
            "workspacePaths": []
        }, timeout_arg=120)
        assert result == {}

        os.remove(tracker)
        os.remove(transcript)

    def test_summary_case_insensitive(self):
        conv_id = f"chk-case-{time.time()}"
        tracker = os.path.join(get_cache_dir(), f"agy_start_{conv_id}")
        with open(tracker, "w") as f:
            f.write(str(time.time() - 300))

        transcript = os.path.join(tempfile.gettempdir(), f"transcript_{conv_id}.jsonl")
        create_transcript(transcript, [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done. summary of Skills Used: rtk, superpowers."}
        ])

        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": transcript,
            "workspacePaths": []
        }, timeout_arg=120)
        assert result == {}

        os.remove(tracker)
        os.remove(transcript)

