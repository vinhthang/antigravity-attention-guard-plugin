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

    def test_subagent_with_token_skipped(self, tmp_path):
        """Token in USER_INPUT should be detected and validated."""
        cache_dir = os.path.join(str(tmp_path), "cache")
        os.makedirs(cache_dir, exist_ok=True)
        token_file = os.path.join(cache_dir, "agy_issued_token_abc-123")
        with open(token_file, "w") as f:
            f.write("parent")

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text(
            '{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "Do task\\n\\n[ANTIGRAVITY_TOKEN:abc-123]"}\n'
        )
        result = run_hook({
            "fullyIdle": True,
            "modelName": "claude-opus-4.6",
            "conversationId": "chk-3",
            "transcriptPath": str(transcript)
        })
        assert result == {"decision": "allow"}

    def test_not_fully_idle_skipped(self):
        result = run_hook({"fullyIdle": False, "modelName": "claude-opus-4.6", "conversationId": "chk-2"})
        assert result == {"decision": "allow"}


class TestStopRejectionLimit:
    def test_max_rejections_then_allow(self, tmp_path):
        conv_id = f"chk-limit-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I did some work but no summary." + " padding" * 30}
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
        assert result == {"decision": "allow"}, "Should allow after max rejections"


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
        assert result == {"decision": "allow"}

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
        assert result == {"decision": "allow"}


class TestContentCap:
    def test_injection_is_capped(self, tmp_path):
        conv_id = f"chk-cap-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "No summary here." + " padding" * 30}
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


class TestSelectiveRuleRefresh:
    def test_no_skills_injected(self, tmp_path):
        """Skills should NOT be loaded - only rules."""
        conv_id = f"chk-norules-{os.getpid()}"
        transcript = tmp_path / f"transcript_{conv_id}.jsonl"
        create_transcript(str(transcript), [
            {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "No summary here." + " padding" * 30}
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
        # Should NOT contain skill-related content
        assert "SKILL.md" not in reason
        # Should contain honest messaging
        assert "reintroduced" in reason.lower() or "rules" in reason.lower()


