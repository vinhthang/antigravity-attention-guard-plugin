import os
import sys
import io
import json
import importlib
import importlib.util
import uuid
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'scripts')))
from common import is_subagent, is_build_command

spec_enforce = importlib.util.spec_from_file_location(
    "enforce_delegation",
    os.path.join(os.path.dirname(__file__), "../scripts/enforce-delegation.py")
)
enforce_mod = importlib.util.module_from_spec(spec_enforce)
sys.modules["enforce_delegation"] = enforce_mod
spec_enforce.loader.exec_module(enforce_mod)
is_test_command = enforce_mod.is_test_command

spec_inject = importlib.util.spec_from_file_location(
    "inject_rules",
    os.path.join(os.path.dirname(__file__), "../scripts/inject-rules.py")
)
inject_mod = importlib.util.module_from_spec(spec_inject)
sys.modules["inject_rules"] = inject_mod
spec_inject.loader.exec_module(inject_mod)

def run_inject_hook(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    inject_mod.main(argv=["inject-rules.py"], stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())

def test_is_subagent_detects_token_in_system_message_step(tmp_path):
    os.environ["AGY_APP_DATA_DIR"] = str(tmp_path)

    import ledger
    importlib.reload(ledger)
    l = ledger.Ledger()

    token = str(uuid.uuid4())
    with l._get_connection() as conn:
        conn.execute("INSERT INTO tokens (token_id) VALUES (?)", (token,))
    payload_data = {
        "token": token,
        "may_delegate": True,
        "remaining_depth": 0,
        "parent_conv_id": "parent_conv",
        "parent_turn_id": "1",
    }
    l.insert_event("parent_conv", "1", "PreToolUse", "0", token, "WORK_PREPARED", json.dumps(payload_data))

    transcript = tmp_path / "transcript.jsonl"
    step_0 = {
        "step_index": 0,
        "source": "SYSTEM",
        "type": "SYSTEM_MESSAGE",
        "content": f"<SYSTEM_MESSAGE>[ANTIGRAVITY_TOKEN:{token}]\nYou are a subagent.</SYSTEM_MESSAGE>",
    }
    transcript.write_text(json.dumps(step_0) + "\n")

    data = {
        "transcriptPath": str(transcript),
        "modelName": "claude-opus-4.6",
        "conversationId": "subagent_conv",
    }
    is_sub, is_verified, depth, p_conv, p_turn = is_subagent(data)
    assert is_sub is True
    assert is_verified is True
    assert depth == 0
    assert p_conv == "parent_conv"
    assert p_turn == "1"

def test_is_test_command_script_boundary():
    # AC-003-1: script args containing "pytest" or "unittest" must NOT trigger is_test_command
    cmd_false = 'rtk python3 /path/to/payload_validator.py --role executor --payload \'{"command_executed": "rtk pytest -v"}\''
    assert is_test_command(cmd_false) is False

    assert is_test_command("rtk python3 -m pytest tests/") is True
    assert is_test_command("rtk python3 -u -m unittest discover") is True
    assert is_test_command("rtk python3 -m pytest.runner") is True
    assert is_test_command("rtk python3 -c 'print(1)'") is False
    assert is_test_command("rtk pytest -v") is True

def test_is_build_command_script_boundary():
    # AC-003-2: script args containing "pip" must NOT trigger is_build_command
    assert is_build_command("rtk python3 script.py --arg pip") is False
    assert is_build_command("rtk python3 -m pip install requests") is True
    assert is_build_command("rtk python3 -m pip.run install requests") is False
    assert is_build_command("rtk python3 setup.py build") is True
    assert is_build_command("rtk python3 setup.py test") is False
    assert is_build_command("rtk pip install requests") is True

def test_inject_rules_denies_traceability_auditor_with_flash(tmp_path, monkeypatch):
    # AC-004-1: TypeName="traceability-auditor" or role with "traceability" denies flash/flash_lite
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)

    payload_by_type = {
        "conversationId": "parent-123",
        "modelName": "claude-opus-4-6",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"TypeName": "traceability-auditor", "Role": "Auditor", "Model": "flash"}]
            }
        }
    }
    res1 = run_inject_hook(payload_by_type)
    assert res1["decision"] == "deny"
    assert "Traceability auditor subagent must use Opus" in res1["reason"]

    payload_by_role = {
        "conversationId": "parent-123",
        "modelName": "claude-opus-4-6",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"TypeName": "self", "Role": "Traceability Auditor", "Model": "flash_lite"}]
            }
        }
    }
    res2 = run_inject_hook(payload_by_role)
    assert res2["decision"] == "deny"
    assert "Traceability auditor subagent must use Opus" in res2["reason"]

def test_inject_rules_preserves_inherit_and_pro_for_traceability_auditor(tmp_path, monkeypatch):
    # AC-004-1: Preserves inherit and pro under a thinking parent
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)

    payload_inherit = {
        "conversationId": "parent-opus",
        "modelName": "claude-opus-4-6",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"TypeName": "traceability-auditor", "Role": "Auditor", "Model": "inherit"}]
            }
        }
    }
    res_inherit = run_inject_hook(payload_inherit)
    assert res_inherit["decision"] == "allow"
    assert res_inherit["overwrite"]["Subagents"][0]["Model"] == "inherit"

    payload_pro = {
        "conversationId": "parent-opus",
        "modelName": "claude-opus-4-6",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"TypeName": "traceability-auditor", "Role": "Auditor", "Model": "pro"}]
            }
        }
    }
    res_pro = run_inject_hook(payload_pro)
    assert res_pro["decision"] == "allow"
    assert res_pro["overwrite"]["Subagents"][0]["Model"] == "pro"

def test_inject_rules_defaults_omitted_model_for_traceability_auditor(tmp_path, monkeypatch):
    # AC-004-1: Defaults omitted Model on traceability-auditor to "pro"
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    import ledger
    importlib.reload(ledger)

    payload_omitted = {
        "conversationId": "parent-opus",
        "modelName": "claude-opus-4-6",
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "Subagents": [{"TypeName": "traceability-auditor", "Role": "Traceability Verification"}]
            }
        }
    }
    res = run_inject_hook(payload_omitted)
    assert res["decision"] == "allow"
    assert res["overwrite"]["Subagents"][0]["Model"] == "pro"

