import pytest
from test_attention_check import run_hook, create_transcript
import tempfile
import os

def test_short_response_bypasses(tmp_path):
    conv_id = f"chk-conv-{os.getpid()}"
    transcript = tmp_path / f"transcript_{conv_id}.jsonl"
    create_transcript(str(transcript), [
        {"source": "MODEL", "type": "PLANNER_RESPONSE", "content": "I am short"}
    ])
    result = run_hook({
        "fullyIdle": True,
        "modelName": "claude-opus-4.6",
        "conversationId": conv_id,
        "transcriptPath": str(transcript),
        "workspacePaths": []
    })
    assert result == {"decision": "allow"}

