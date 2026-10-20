import os
import sys
import json
import subprocess
from pathlib import Path
import pytest

# Ensure scripts directory is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from surface_validator import (
    PluginSurfaceSpec,
    DEFAULT_SURFACE,
    read_plugin_tree,
    always_on_text,
    all_rules_text,
    skill_names,
    autotrigger,
    check_hooks,
    validate_plugin_surface,
    diff_summary,
)
from deploy_plugin import verify_source_bundle, CANONICAL_SOURCE

ATTENTION_GUARD_DIR = Path("/Users/thanghoang/.gemini/config/plugins/attention-guard")
AGENT_TRANSLATOR_DIR = Path("/Users/thanghoang/.gemini/config/plugins/agent-translator")


def test_valid_plugin_surface_attention_guard():
    assert ATTENTION_GUARD_DIR.is_dir()
    ok, errs, census = validate_plugin_surface(ATTENTION_GUARD_DIR)
    assert ok is True, f"Surface errors in attention-guard: {errs}"
    assert len(errs) == 0
    assert census["valid"] is True
    assert "attention-metrics" in census["skills"]
    assert census["always_on_chars"] <= census["always_on_max"]


def test_valid_plugin_surface_agent_translator():
    assert AGENT_TRANSLATOR_DIR.is_dir()
    ok, errs, census = validate_plugin_surface(AGENT_TRANSLATOR_DIR)
    assert ok is True, f"Surface errors in agent-translator: {errs}"
    assert len(errs) == 0
    assert census["valid"] is True
    assert census["skill_count"] == 5
    assert "translate" in census["skills"]
    assert "translate-book" in census["skills"]
    assert "translate-zh-book" in census["skills"]
    assert "en-vi-book-translation-review" in census["skills"]
    assert "summarize-book" in census["skills"]
    assert census["always_on_chars"] <= census["always_on_max"]


def test_always_on_max_cap_violation(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    # 250 characters of rule text
    (rules_dir / "AGENTS.md").write_text("x" * 250, encoding="utf-8")

    ok, errs, census = validate_plugin_surface(tmp_path, always_on_max=100)
    assert ok is False
    assert any("Always-on rules exceed budget" in e for e in errs)
    assert census["valid"] is False
    assert census["always_on_chars"] == 250
    assert census["always_on_max"] == 100


def test_empty_always_on_file_rejection(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text("   \n\t  \n", encoding="utf-8")

    ok, errs, _ = validate_plugin_surface(tmp_path)
    assert ok is False
    assert any("is empty" in e for e in errs)


def test_skill_missing_description(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text(
        "Always follow instructions. Consult skill `test-skill`.\n",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skills" / "test-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: test-skill\n---\n# Test Skill Documentation\n",
        encoding="utf-8",
    )

    ok, errs, _ = validate_plugin_surface(tmp_path)
    assert ok is False
    assert any("missing non-empty 'description:'" in e for e in errs)


def test_skill_mismatched_name(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text(
        "Consult skill `alpha-skill`.\n",
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skills" / "alpha-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: beta-skill\ndescription: Does alpha work.\n---\n",
        encoding="utf-8",
    )

    ok, errs, _ = validate_plugin_surface(tmp_path)
    assert ok is False
    assert any("mismatched name 'beta-skill'" in e for e in errs)


def test_untriggered_skill_and_autotrigger(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    agents_file = rules_dir / "AGENTS.md"
    agents_file.write_text(
        '<rule name="test">\n<instructions>\n- Base instruction.\n</instructions>\n</rule>\n',
        encoding="utf-8",
    )
    skill_dir = tmp_path / "skills" / "auto-skill"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: auto-skill\ndescription: Auto triggers an action.\n---\n",
        encoding="utf-8",
    )

    # Step 1: without repair_triggers, validation fails because auto-skill is untriggered
    ok, errs, _ = validate_plugin_surface(tmp_path, repair_triggers=False)
    assert ok is False
    assert any("Skill 'auto-skill' is not triggered in any rules/*.md" in e for e in errs)

    # Step 2: with repair_triggers=True, autotrigger injects the trigger line and passes
    ok2, errs2, _ = validate_plugin_surface(tmp_path, repair_triggers=True)
    assert ok2 is True, f"Expected success after repair, got: {errs2}"
    assert len(errs2) == 0

    repaired_content = agents_file.read_text(encoding="utf-8")
    assert "consult skill `auto-skill`" in repaired_content
    # Verified it was placed before </instructions>
    assert repaired_content.index("consult skill `auto-skill`") < repaired_content.index("</instructions>")


def test_missing_referenced_script(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    (rules_dir / "AGENTS.md").write_text(
        "Execute via `python3 scripts/nonexistent.py`\n",
        encoding="utf-8",
    )

    ok, errs, _ = validate_plugin_surface(tmp_path)
    assert ok is False
    assert any("scripts/nonexistent.py" in e and "not found in plugin tree" in e for e in errs)


def test_invalid_python_syntax(tmp_path):
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "bad_syntax.py").write_text(
        "def broken_syntax(:\n    pass\n",
        encoding="utf-8",
    )

    ok, errs, _ = validate_plugin_surface(tmp_path)
    assert ok is False
    assert any("Python syntax error in 'scripts/bad_syntax.py'" in e for e in errs)


def test_check_hooks_validation(tmp_path):
    # 1. Invalid hook event
    bad_event_json = json.dumps({"hooks": {"UnknownEvent": [{"type": "command", "command": "echo 1"}]}})
    errs = []
    check_hooks(DEFAULT_SURFACE, bad_event_json, {}, errs)
    assert any("Invalid hook event 'UnknownEvent'" in e for e in errs)

    # 2. Invalid hook type
    bad_type_json = json.dumps({"hooks": {"PreToolUse": [{"type": "shell", "command": "echo 1"}]}})
    errs = []
    check_hooks(DEFAULT_SURFACE, bad_type_json, {}, errs)
    assert any("must have type 'command'" in e for e in errs)

    # 3. Missing hook script
    missing_script_json = json.dumps({
        "hooks": {
            "PreToolUse": [
                {
                    "type": "command",
                    "command": "/usr/bin/env python3 ./scripts/ghost.py",
                }
            ]
        }
    })
    errs = []
    check_hooks(DEFAULT_SURFACE, missing_script_json, {}, errs)
    assert any("references missing script 'scripts/ghost.py'" in e for e in errs)

    # 4. Valid grouped hooks
    valid_grouped_json = json.dumps({
        "my-plugin": {
            "PreInvocation": [
                {
                    "type": "command",
                    "command": "/usr/bin/env python3 ./scripts/active.py",
                }
            ]
        }
    })
    errs = []
    tree = {"scripts/active.py": "print('ok')\n"}
    check_hooks(DEFAULT_SURFACE, valid_grouped_json, tree, errs)
    assert len(errs) == 0


def test_diff_summary():
    before = {
        "rules/AGENTS.md": "abc",
        "scripts/old.py": "print(1)",
        "scripts/stay.py": "same",
    }
    after = {
        "rules/AGENTS.md": "abcdefgh",  # +5 chars
        "scripts/new.py": "print(2)",
        "scripts/stay.py": "same",
    }
    diff = diff_summary(DEFAULT_SURFACE, before, after)
    assert diff["added"] == ["scripts/new.py"]
    assert diff["removed"] == ["scripts/old.py"]
    assert diff["modified"] == ["rules/AGENTS.md"]
    assert diff["always_on_char_delta"] == 5


def test_deploy_plugin_verify_only():
    valid, missing = verify_source_bundle(CANONICAL_SOURCE)
    assert valid is True, f"verify_source_bundle failed: {missing}"
    assert len(missing) == 0

    cmd = [sys.executable, str(SCRIPTS_DIR / "deploy_plugin.py"), "--verify-only"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert res.returncode == 0
    assert "Source bundle is complete and valid." in res.stdout


def test_always_on_text_fallback_to_all_rules():
    surface = PluginSurfaceSpec(always_on=("rules/AGENTS.md",))
    tree_with_custom_rule = {
        "rules/spec-standard.md": "# Spec Standard Rule\nDetails here.\n",
        "scripts/helper.py": "print('ok')\n",
    }
    # When rules/AGENTS.md is absent, falls back to all_rules_text
    aon = always_on_text(surface, tree_with_custom_rule)
    assert aon == "# Spec Standard Rule\nDetails here.\n"

    # When rules/AGENTS.md is present, uses surface.always_on
    tree_with_agents = {
        "rules/AGENTS.md": "# Agents Rule\n",
        "rules/spec-standard.md": "# Spec Standard Rule\n",
    }
    aon2 = always_on_text(surface, tree_with_agents)
    assert aon2 == "# Agents Rule\n"


def test_validate_surface_with_custom_rule_file(tmp_path):
    rules_dir = tmp_path / "rules"
    rules_dir.mkdir()
    rule_content = "# Spec Standard Rule\n" * 5
    (rules_dir / "spec-standard.md").write_text(rule_content, encoding="utf-8")
    ok, errs, census = validate_plugin_surface(tmp_path)
    assert ok is True, f"Errors: {errs}"
    assert census["always_on_chars"] == len(rule_content)
