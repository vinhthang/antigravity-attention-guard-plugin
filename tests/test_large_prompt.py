import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from common import is_subagent

def test_large_prompt_token_present(tmp_path):
    cache_dir = os.path.join(str(tmp_path), "cache")
    os.environ["AGY_APP_DATA_DIR"] = str(tmp_path)
    os.makedirs(cache_dir, exist_ok=True)

    token = "1234-abcd"
    token_file = os.path.join(cache_dir, f"agy_issued_token_{token}")
    with open(token_file, "w") as f:
        f.write("parent")

    large_prompt = "A" * 9000
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        f'{{"source": "USER_EXPLICIT", "type": "USER_INPUT", "content": "[ANTIGRAVITY_TOKEN:{token}]\\n\\n{large_prompt}"}}\n'
    )

    data = {"transcriptPath": str(transcript)}
    assert is_subagent(data) is True

