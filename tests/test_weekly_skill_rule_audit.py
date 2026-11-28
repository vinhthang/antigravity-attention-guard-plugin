import json
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from weekly_skill_rule_audit import _check_skill_links, run_weekly_audit


def _write_minimal_config(cfg: Path) -> None:
    rules_dir = cfg / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "rtk.md").write_text("---\ntrigger: always_on\n---\n# RTK\n", encoding="utf-8")


def _create_denials_db(db_path: Path, now_ts: float) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE events (event_id TEXT, type TEXT, payload TEXT, created_at REAL)"
        )
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            (
                "ev-1",
                "PRIMARY_TOOL_DENIED",
                json.dumps({"tool": "run_command", "is_sub": False, "reason": "blocked"}),
                now_ts - 3600,
            ),
        )
        conn.commit()


def test_default_db_path_uses_agy_app_data_dir(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    brain = tmp_path / "brain"
    app_data = tmp_path / "antigravity"
    _write_minimal_config(cfg)
    brain.mkdir()
    _create_denials_db(app_data / "attention_guard.db", time.time())

    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data))
    report = run_weekly_audit(config_root=cfg, brain_root=brain, db_path=None, days=7)

    assert report["denials_7d"]["total"] == 1
    assert report["denials_7d"]["by_tool"] == {"run_command": 1}


def test_check_skill_links_ignores_code_spans_and_ellipsis_but_catches_real_broken(tmp_path):
    cfg = tmp_path / "config"
    skill_dir = cfg / "skills" / "demo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "existing.md").write_text("# OK\n", encoding="utf-8")
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(
        "---\n"
        "name: demo\n"
        "description: Demo skill\n"
        "---\n"
        "Valid link: [ok](existing.md)\n"
        "Inline code anchor: `![Figure](...)` and `![Figure](images/...)`\n"
        "```markdown\n"
        "![Fenced](does/not/exist.png)\n"
        "```\n"
        "Real broken link: [broken](missing.md)\n",
        encoding="utf-8",
    )

    errs = _check_skill_links(skill_md, cfg)
    assert any("missing.md" in e for e in errs)
    assert not any("'...'" in e or "images/..." in e or "does/not/exist.png" in e for e in errs)


def test_scan_transcripts_excludes_self_echo_and_stale_entries(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    brain = tmp_path / "brain"
    app_data = tmp_path / "antigravity"
    _write_minimal_config(cfg)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data))

    tfile = brain / "conv-1" / ".system_generated" / "logs" / "transcript.jsonl"
    tfile.parent.mkdir(parents=True)

    now = time.time()
    recent_iso = datetime.fromtimestamp(now - 3600, tz=timezone.utc).isoformat()
    stale_iso = datetime.fromtimestamp(now - 30 * 86400, tz=timezone.utc).isoformat()

    entries = [
        # Stale error inside a recently touched long-lived transcript (must be excluded)
        {"created_at": stale_iso, "content": "Error: unknown flag: --stale-flag\n"},
        {"created_at": stale_iso, "content": "Error: unknown flag: --stale-flag\n"},
        # Audit JSON self-echo (must be excluded)
        {
            "created_at": recent_iso,
            "content": json.dumps({"repeated_cli_errors": [{"pattern": "unknown flag: --echo-flag", "count": 3}]}),
        },
        {
            "created_at": recent_iso,
            "content": json.dumps({"repeated_cli_errors": [{"pattern": "unknown flag: --echo-flag", "count": 4}]}),
        },
        # Regex source code echo (must be excluded)
        {"created_at": recent_iso, "content": '_CLI_ERROR_RE = re.compile(r"(unknown flag: --src)")'},
        {"created_at": recent_iso, "content": '_CLI_ERROR_RE = re.compile(r"(unknown flag: --src)")'},
        # Real recent repeated CLI error (must be included)
        {"created_at": recent_iso, "content": "Error: unknown flag: --real-flag\n"},
        {"created_at": recent_iso, "content": "Error: unknown flag: --real-flag\n"},
    ]
    tfile.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")

    report = run_weekly_audit(config_root=cfg, brain_root=brain, days=7, min_repeat=2)
    patterns = {item["pattern"]: item["count"] for item in report["repeated_cli_errors"]}

    assert patterns == {"unknown flag: --real-flag": 2}


def test_audit_honors_plugin_manifest_skills_paths(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    brain = tmp_path / "brain"
    app_data = tmp_path / "antigravity"
    _write_minimal_config(cfg)
    brain.mkdir()
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data))

    pdir = cfg / "plugins" / "custom-plugin"
    (pdir / "antigravity" / "skills" / "nested-skill").mkdir(parents=True)
    (pdir / "plugin.json").write_text(
        json.dumps({"name": "custom-plugin", "skills": ["./antigravity/skills"]}),
        encoding="utf-8",
    )
    (pdir / "antigravity" / "skills" / "nested-skill" / "SKILL.md").write_text(
        "---\nname: nested-skill\ndescription: Custom manifest path\n---\nBroken: [missing](nope.md)\n",
        encoding="utf-8",
    )

    report = run_weekly_audit(config_root=cfg, brain_root=brain, days=7)
    assert report["skills"]["total_skills"] == 1
    assert "nested-skill" in report["skills"]["unused_skills"]
    assert any("nope.md" in err for err in report["errors"])


def test_scan_transcripts_excludes_prior_audit_conversations_and_planner_prose(tmp_path, monkeypatch):
    cfg = tmp_path / "config"
    brain = tmp_path / "brain"
    app_data = tmp_path / "antigravity"
    _write_minimal_config(cfg)
    monkeypatch.setenv("AGY_APP_DATA_DIR", str(app_data))

    now = time.time()
    recent_iso = datetime.fromtimestamp(now - 1800, tz=timezone.utc).isoformat()

    # 1. Prior weekly audit conversation echoing old errors in shell summaries
    audit_log = brain / "audit-conv" / ".system_generated" / "logs" / "transcript.jsonl"
    audit_log.parent.mkdir(parents=True)
    audit_entries = [
        {"created_at": recent_iso, "type": "USER_INPUT", "content": "Run Weekly Skills & Rules Health Audit via weekly_skill_rule_audit.py"},
        {"created_at": recent_iso, "type": "GENERIC", "content": "PATTERN: unknown flag: --echoed-only\nPATTERN: unknown flag: --echoed-only\n"},
    ]
    audit_log.write_text("\n".join(json.dumps(e) for e in audit_entries) + "\n", encoding="utf-8")

    # 2. Normal conversation with PLANNER_RESPONSE prose vs real GENERIC tool output
    normal_log = brain / "work-conv" / ".system_generated" / "logs" / "transcript.jsonl"
    normal_log.parent.mkdir(parents=True)
    normal_entries = [
        {"created_at": recent_iso, "type": "PLANNER_RESPONSE", "content": "Fixed crash `unrecognized arguments: --prose-only` in doc."},
        {"created_at": recent_iso, "type": "PLANNER_RESPONSE", "content": "Verified `unrecognized arguments: --prose-only` is resolved."},
        {"created_at": recent_iso, "type": "GENERIC", "content": "Error: unknown flag: --real-v2\n"},
        {"created_at": recent_iso, "type": "GENERIC", "content": "Error: unknown flag: --real-v2\n"},
    ]
    normal_log.write_text("\n".join(json.dumps(e) for e in normal_entries) + "\n", encoding="utf-8")

    report = run_weekly_audit(config_root=cfg, brain_root=brain, days=7, min_repeat=2)
    patterns = {item["pattern"]: item["count"] for item in report["repeated_cli_errors"]}
    assert patterns == {"unknown flag: --real-v2": 2}
