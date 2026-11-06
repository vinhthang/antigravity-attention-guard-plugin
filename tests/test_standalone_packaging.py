import os
import sys
import json
import io
import shutil
import subprocess
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import importlib.util

spec_enf = importlib.util.spec_from_file_location(
    "enforce_delegation", str(SCRIPTS_DIR / "enforce-delegation.py")
)
enforce_delegation = importlib.util.module_from_spec(spec_enf)
spec_enf.loader.exec_module(enforce_delegation)

spec_inj = importlib.util.spec_from_file_location(
    "inject_rules", str(SCRIPTS_DIR / "inject-rules.py")
)
inject_rules = importlib.util.module_from_spec(spec_inj)
spec_inj.loader.exec_module(inject_rules)

from surface_validator import validate_plugin_surface, DEFAULT_SURFACE


def run_enforce(payload):
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    enforce_delegation.main(stdin=stdin, stdout=stdout)
    return json.loads(stdout.getvalue().strip())


def test_req_033_json_gate_in_enforce_delegation(tmp_path, monkeypatch):
    """REQ-033: enforce-delegation validates Message is JSON dict and runs verify_cmd."""
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("AGY_DISABLE_JSON_GATE", raising=False)

    p_transcript = tmp_path / "transcript.jsonl"
    p_transcript.write_text(json.dumps({"source": "USER", "type": "USER_INPUT", "step_index": 1, "content": "hi"}) + "\n")

    # 1. Non-JSON string Message -> deny
    res1 = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": "Here is plain text instead of JSON"
            }
        }
    })
    assert res1["decision"] == "deny"
    assert "Handoff MUST be valid JSON. No conversational fluff." in res1["reason"]

    # 2. JSON list instead of dict -> deny
    res2 = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps(["not", "a", "dict"])
            }
        }
    })
    assert res2["decision"] == "deny"
    assert "Handoff MUST be valid JSON. No conversational fluff." in res2["reason"]

    # 3. Failing verify_cmd -> deny with Verification Failed
    res3 = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps({"task": "run", "verify_cmd": "exit 42"})
            }
        }
    })
    assert res3["decision"] == "deny"
    assert "Verification Failed:" in res3["reason"]

    # 4. Passing verify_cmd with valid JSON dict -> allow
    res4 = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps({"task": "run", "verify_cmd": "exit 0"})
            }
        }
    })
    assert res4["decision"] == "allow"

    # 5. Non-string verify_cmd -> deny
    res5_type = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps({"task": "run", "verify_cmd": 12345})
            }
        }
    })
    assert res5_type["decision"] == "deny"
    assert "verify_cmd must be a string" in res5_type["reason"]

    # 6. Destructive command in verify_cmd -> deny
    res6_dest = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps({"task": "run", "verify_cmd": "git reset --hard"})
            }
        }
    })
    assert res6_dest["decision"] == "deny"
    assert "destructive command rejected" in res6_dest["reason"]

    # 7. Thinking model Primary Agent executing test command via verify_cmd -> deny
    res7_think = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "modelName": "Opus 4",
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": json.dumps({"task": "run", "verify_cmd": "pytest tests/"})
            }
        }
    })
    assert res7_think["decision"] == "deny"
    assert "Primary Agent under thinking model is forbidden" in res7_think["reason"]

    # 8. AGY_DISABLE_JSON_GATE=1 escape hatch -> allow plain text
    monkeypatch.setenv("AGY_DISABLE_JSON_GATE", "1")
    res8 = run_enforce({
        "conversationId": "parent-1",
        "transcriptPath": str(p_transcript),
        "toolCall": {
            "name": "send_message",
            "args": {
                "Recipient": "worker-1",
                "Message": "Conversational plain text message allowed when gate disabled"
            }
        }
    })
    assert res8["decision"] == "allow"


def test_req_034_templates_resolution_in_inject_rules(tmp_path, monkeypatch):
    """REQ-034: templates/ directory hosts subagent templates, with fallback to rules/."""
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(tmp_path))
    assert (REPO_ROOT / "templates" / "EXECUTOR.md").is_file(), "templates/EXECUTOR.md must exist"
    assert (REPO_ROOT / "templates" / "COORDINATOR.md").is_file(), "templates/COORDINATOR.md must exist"
    # rules/ must NOT contain EXECUTOR.md or COORDINATOR.md
    assert not (REPO_ROOT / "rules" / "EXECUTOR.md").exists(), "rules/EXECUTOR.md must be moved to templates/"
    assert not (REPO_ROOT / "rules" / "COORDINATOR.md").exists(), "rules/COORDINATOR.md must be moved to templates/"

    # Test executing inject_rules.main with templates/ resolution
    payload = {
        "conversationId": "parent-1",
        "stepIdx": 1,
        "toolCall": {
            "name": "invoke_subagent",
            "args": {
                "TypeName": "self",
                "Role": "Test Executor",
                "Prompt": "Execute task"
            }
        }
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    inject_rules.main(stdin=stdin, stdout=stdout)
    out = json.loads(stdout.getvalue().strip())
    assert out["decision"] == "allow"
    injected_prompt = out["overwrite"]["Prompt"]
    assert "[ANTIGRAVITY_TOKEN:" in injected_prompt
    assert "Governs Executor subagents" in injected_prompt

    # Test default sys.stdin/sys.stdout when None passed
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    inject_rules.main()
    out_def = json.loads(fake_stdout.getvalue().strip())
    assert out_def["decision"] == "allow"

    # Test CLI invocation (__name__ == '__main__')
    res_cli = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "inject-rules.py")],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env={**os.environ, "AGY_APP_DATA_DIR": str(tmp_path)}
    )
    assert res_cli.returncode == 0
    out_cli = json.loads(res_cli.stdout.strip())
    assert out_cli["decision"] == "allow"


def test_req_034_consolidated_agents_md_budget_and_cleanliness():
    """REQ-034: rules/AGENTS.md is consolidated, <= 8000 chars, no /Users/thanghoang paths, and has skill triggers."""
    agents_file = REPO_ROOT / "rules" / "AGENTS.md"
    assert agents_file.is_file()
    content = agents_file.read_text(encoding="utf-8")

    assert len(content) <= 8000, f"rules/AGENTS.md must be <= 8000 chars, got {len(content)}"
    assert "/Users/thanghoang" not in content, "rules/AGENTS.md must not contain hardcoded user home paths"
    assert "consult skill `attention-metrics`" in content
    assert "consult skill `git-worktree-sandbox`" in content
    assert "agent-delegation" in content
    assert "explicit-approval" in content
    assert "no-error-suppression" in content
    assert "reasoning-quality" in content


def test_req_035_git_worktree_sandbox_bundled_and_portable():
    """REQ-035: git-worktree-sandbox bundled with portable skill discovery."""
    skill_dir = REPO_ROOT / "skills" / "git-worktree-sandbox"
    assert (skill_dir / "SKILL.md").is_file()
    assert (skill_dir / "scripts" / "worktree_manager.py").is_file()

    # Zero /Users/thanghoang across all rules, templates, skills, scripts, hooks.json
    for check_dir in ["rules", "templates", "skills", "scripts"]:
        dp = REPO_ROOT / check_dir
        if dp.is_dir():
            for f in dp.rglob("*"):
                if f.is_file() and f.suffix in (".md", ".py", ".json", ".sh"):
                    txt = f.read_text(encoding="utf-8", errors="replace")
                    assert "/Users/thanghoang" not in txt, f"Hardcoded user path found in {f.relative_to(REPO_ROOT)}"

    hooks_txt = (REPO_ROOT / "hooks.json").read_text(encoding="utf-8")
    assert "/Users/thanghoang" not in hooks_txt


def test_req_036_marketplace_manifest_and_assets():
    """REQ-036: plugin.json completeness, assets/logo.svg, LICENSE, and .gitignore hygiene."""
    pjson_path = REPO_ROOT / "plugin.json"
    assert pjson_path.is_file()
    meta = json.loads(pjson_path.read_text(encoding="utf-8"))

    assert meta["name"] == "attention-guard"
    assert meta["displayName"] == "Attention Guard"
    assert meta["version"] == "1.0.0"
    assert "description" in meta and len(meta["description"]) > 20
    assert meta["logo"] == "assets/logo.svg"
    assert isinstance(meta.get("author"), dict) and meta["author"]["name"] == "Sam Hoang"
    assert "homepage" in meta and "repository" in meta
    assert isinstance(meta.get("suggestedPrompts"), list) and len(meta["suggestedPrompts"]) == 3

    logo_path = REPO_ROOT / "assets" / "logo.svg"
    assert logo_path.is_file()
    logo_txt = logo_path.read_text(encoding="utf-8")
    assert "<svg" in logo_txt and "</svg>" in logo_txt

    license_path = REPO_ROOT / "LICENSE"
    assert license_path.is_file()
    assert "MIT License" in license_path.read_text(encoding="utf-8")

    # Clean repo root: no stray scratch files
    for stray in ["task.md", "REVERIFICATION_REPORT.md", "review.json", ".coverage"]:
        assert not (REPO_ROOT / stray).exists(), f"Stray file {stray} must not exist in repository root"


def test_req_037_global_config_cleanup():
    """REQ-037: Local ~/.gemini/config/ has duplicate hooks, rules, and deprecated ast-gate removed."""
    home_config = Path.home() / ".gemini" / "config"
    hooks_file = home_config / "hooks.json"
    if hooks_file.is_file():
        hooks_data = json.loads(hooks_file.read_text(encoding="utf-8"))
        assert "json-gate" not in str(hooks_data)
        assert "ast-gate" not in str(hooks_data)

    scripts_dir = home_config / "scripts"
    assert not (scripts_dir / "ast-gate.py").exists(), "ast-gate.py must be removed"
    assert not (REPO_ROOT / "scripts" / "json-gate.py").exists()
    assert not (REPO_ROOT / "scripts" / "spec-gate.py").exists()

    rules_dir = home_config / "rules"
    assert not (rules_dir / "no-error-suppression.md").exists(), "global duplicate no-error-suppression.md must be removed"
    assert not (rules_dir / "reasoning-quality.md").exists(), "global duplicate reasoning-quality.md must be removed"

    assert not (home_config / "skills" / "git-worktree-sandbox").exists(), "global duplicate git-worktree-sandbox skill must be removed"

    ast_grep_skill = home_config / "skills" / "ast-grep-toolkit" / "SKILL.md"
    if ast_grep_skill.is_file():
        content = ast_grep_skill.read_text(encoding="utf-8")
        assert "ast-gate.py" not in content
