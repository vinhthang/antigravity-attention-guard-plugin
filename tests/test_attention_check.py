#!/usr/bin/env python3
import subprocess
import json
import os
import tempfile
import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "attention-check.py")


@pytest.fixture(autouse=True)
def setup_test_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))


def run_hook(payload):
    env = os.environ.copy()
    result = subprocess.run(
        ["python3", SCRIPT],
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
    def test_subagent_skipped_flash(self):
        result = run_hook({"fullyIdle": True, "modelName": "gemini-2.0-flash", "conversationId": "chk-1"})
        assert result == {}

    def test_subagent_with_marker_skipped(self, tmp_path):
        """Marker in USER_INPUT (real Antigravity format) should be detected."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do task\\n\\n[ANTIGRAVITY_SUBAGENT:conv-123:456]"}\n'
        )
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
    def test_max_rejections_then_allow(self, tmp_path):
        conv_id = f"chk-limit-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I did some work but no summary."}
        ])

        payload = {
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        }

        for i in range(3):
            result = run_hook(payload)
            assert result.get("decision") == "continue", f"Rejection {i+1} should block"

        result = run_hook(payload)
        assert result == {}, "Should allow after max rejections"


class TestSkillsSummaryDetection:
    def test_summary_present_passes(self, tmp_path):
        conv_id = f"chk-pass-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done. Summary of skills used: rtk, superpowers."}
        ])
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        })
        assert result == {}

    def test_summary_case_insensitive(self, tmp_path):
        conv_id = f"chk-case-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "Done. summary of Skills Used: rtk."}
        ])
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        })
        assert result == {}


class TestContentCap:
    def test_injection_is_capped(self, tmp_path):
        conv_id = f"chk-cap-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "No summary here."}
        ])
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": conv_id,
            "transcriptPath": str(transcript),
            "workspacePaths": []
        })
        assert result.get("decision") == "continue"
        reason = result.get("reason", "")
        # Reason should exist and be capped
        assert len(reason.encode("utf-8")) <= 16384 + 200  # Allow some buffer for truncation notice
