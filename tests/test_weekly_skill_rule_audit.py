#!/usr/bin/env python3
"""TDD tests for REQ-048: read-only weekly skills & rules health audit CLI."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import weekly_skill_rule_audit as audit


def _make_healthy_tree(tmp_path: Path):
    cfg = tmp_path / "config"
    rules = cfg / "rules"
    skills = cfg / "skills"
    plugins = cfg / "plugins"
    brain = tmp_path / "brain"
    rules.mkdir(parents=True)
    skills.mkdir(parents=True)
    plugins.mkdir(parents=True)
    brain.mkdir(parents=True)

    (rules / "core.md").write_text("---\ntrigger: always_on\n---\n# Core rule\nAlways concise.\n", encoding="utf-8")
    (rules / "lazy.md").write_text("---\ntrigger: model_decision\ndescription: When reviewing foo.\n---\n# Lazy\n", encoding="utf-8")

    s1 = skills / "alpha-tool"
    (s1 / "references").mkdir(parents=True)
    (s1 / "references" / "guide.md").write_text("# Guide\n", encoding="utf-8")
    (s1 / "SKILL.md").write_text(
        "---\nname: alpha-tool\ndescription: Run alpha tool.\n---\nSee [guide](references/guide.md).\n",
        encoding="utf-8",
    )

    s2 = skills / "beta-idle"
    s2.mkdir(parents=True)
    (s2 / "SKILL.md").write_text(
        "---\nname: beta-idle\ndescription: Unused idle skill.\n---\nRun beta.\n",
        encoding="utf-8",
    )

    p1 = plugins / "sample-plugin"
    (p1 / "rules").mkdir(parents=True)
    (p1 / "skills" / "p-skill").mkdir(parents=True)
    (p1 / "plugin.json").write_text('{"name":"sample-plugin","description":"Sample plugin"}', encoding="utf-8")
    (p1 / "rules" / "sample.md").write_text(
        "---\ntrigger: model_decision\ndescription: Consult skill `p-skill`.\n---\nConsult skill `p-skill`.\n",
        encoding="utf-8",
    )
    (p1 / "skills" / "p-skill" / "SKILL.md").write_text(
        "---\nname: p-skill\ndescription: Plugin skill.\n---\nBody.\n",
        encoding="utf-8",
    )

    # Recent transcript using alpha-tool cleanly
    t_dir = brain / "conv-recent" / ".system_generated" / "logs"
    t_dir.mkdir(parents=True)
    (t_dir / "transcript.jsonl").write_text(
        json.dumps({"tool_calls": [{"name": "read_file", "args": {"Path": str(s1 / "SKILL.md")}}]}) + "\n",
        encoding="utf-8",
    )

    # SQLite DB with 1 recent denial and 1 old denial
    db = tmp_path / "attention_guard.db"
    now = time.time()
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE events (event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, created_at REAL)")
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            ("ev-1", "PRIMARY_TOOL_DENIED", json.dumps({"tool": "run_command", "reason": "kubectl qa2"}), now - 60),
        )
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?)",
            ("ev-old", "PRIMARY_TOOL_DENIED", json.dumps({"tool": "write_file", "reason": "old"}), now - 20 * 86400),
        )
        conn.commit()

    return cfg, brain, db


def test_healthy_audit_reports_clean_budget_usage_and_denials(tmp_path):
    cfg, brain, db = _make_healthy_tree(tmp_path)
    report = audit.run_weekly_audit(config_root=cfg, brain_root=brain, db_path=db, days=7, always_on_budget=8000, min_repeat=2)

    assert report["valid"] is True
    assert report["errors"] == []
    assert report["rules"]["always_on_count"] == 1
    assert report["rules"]["always_on_injected_chars"] == len("# Core rule\nAlways concise.")
    assert report["rules"]["model_decision_count"] == 2
    assert report["skills"]["skill_usage"]["alpha-tool"] == 1
    assert "beta-idle" in report["skills"]["unused_skills"]
    assert "alpha-tool" not in report["skills"]["unused_skills"]
    assert report["denials_7d"]["total"] == 1
    assert report["denials_7d"]["by_tool"] == {"run_command": 1}
    assert report["repeated_cli_errors"] == []


def test_broken_links_bad_trigger_budget_and_repeated_cli_errors(tmp_path):
    cfg, brain, db = _make_healthy_tree(tmp_path)
    # 1. Invalid rule trigger
    (cfg / "rules" / "bad.md").write_text("---\ntrigger: alwaysOn\ndescription: Bad trigger.\n---\n# Bad\n", encoding="utf-8")
    # 2. Broken skill reference
    (cfg / "skills" / "alpha-tool" / "SKILL.md").write_text(
        "---\nname: alpha-tool\ndescription: Broken ref.\n---\nSee [missing](references/missing.md) and ~/.gemini/config/skills/alpha-tool/scripts/nope.py.\n",
        encoding="utf-8",
    )
    # 3. Transcript friction: 2 identical recent errors + 1 unique recent + 2 old expired errors
    t_recent = brain / "conv-2" / ".system_generated" / "logs" / "transcript.jsonl"
    t_recent.parent.mkdir(parents=True)
    t_recent.write_text(
        json.dumps({"content": "usage: cli\nerror: unrecognized arguments: --stale-flag\n"}) + "\n"
        + json.dumps({"content": "error: unrecognized arguments: --stale-flag\n"}) + "\n"
        + json.dumps({"content": "error: no such option: --one-off\n"}) + "\n",
        encoding="utf-8",
    )
    t_old = brain / "conv-old" / ".system_generated" / "logs" / "transcript.jsonl"
    t_old.parent.mkdir(parents=True)
    t_old.write_text(
        json.dumps({"content": "error: unknown flag: --expired\nerror: unknown flag: --expired\n"}) + "\n",
        encoding="utf-8",
    )
    old_ts = time.time() - 10 * 86400
    os.utime(t_old, (old_ts, old_ts))

    # Small budget forces overflow failure too
    report = audit.run_weekly_audit(config_root=cfg, brain_root=brain, db_path=db, days=7, always_on_budget=5, min_repeat=2)
    assert report["valid"] is False
    joined_errs = "\n".join(report["errors"])
    assert "Invalid rule trigger" in joined_errs
    assert "missing" in joined_errs
    assert "budget exceeded" in joined_errs
    assert len(report["repeated_cli_errors"]) == 1
    assert report["repeated_cli_errors"][0]["pattern"] == "unrecognized arguments: --stale-flag"
    assert report["repeated_cli_errors"][0]["count"] == 2


def test_cli_json_exit_codes_and_missing_optional_paths(tmp_path):
    cfg, brain, db = _make_healthy_tree(tmp_path)
    missing_brain = tmp_path / "no-brain"
    missing_db = tmp_path / "no-db.sqlite"

    proc_ok = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "weekly_skill_rule_audit.py"),
            "--config-root", str(cfg),
            "--brain-root", str(missing_brain),
            "--db-path", str(missing_db),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert proc_ok.returncode == 0
    data_ok = json.loads(proc_ok.stdout)
    assert data_ok["valid"] is True
    assert data_ok["denials_7d"]["total"] == 0

    (cfg / "rules" / "bad.md").write_text("---\ntrigger: model_decision\n---\nNo desc\n", encoding="utf-8")
    proc_bad = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "weekly_skill_rule_audit.py"),
            "--config-root", str(cfg),
            "--brain-root", str(missing_brain),
            "--db-path", str(missing_db),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert proc_bad.returncode == 1
    assert json.loads(proc_bad.stdout)["valid"] is False
