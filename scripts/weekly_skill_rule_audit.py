#!/usr/bin/env python3
"""Read-only Weekly Skills & Rules Health Audit CLI (REQ-048)."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Optional

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from surface_validator import (
    VALID_RULE_TRIGGERS,
    extract_frontmatter,
    is_always_on_rule,
    validate_plugin_surface,
)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_MD_LINK_RE = re.compile(r"\[[^\]]+\]\(([^)#?\s]+)\)")
_GLOBAL_SKILL_REF_RE = re.compile(r"~/.gemini/config/skills/([A-Za-z0-9._/-]+)")
_CLI_ERROR_RE = re.compile(
    r"((?:unrecognized arguments|unknown flag|no such option|command not found|can't open file):?\s*[^\n\"\\`]+)",
    re.IGNORECASE,
)


def _strip_frontmatter(text: str) -> tuple[bool, str]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return False, text
    return True, text[match.end() :]


def _audit_rules(config_root: Path, always_on_budget: int) -> tuple[dict[str, Any], list[str]]:
    errors: list[str] = []
    rule_files: list[Path] = []

    global_rules_dir = config_root / "rules"
    if global_rules_dir.is_dir():
        rule_files.extend(sorted(global_rules_dir.glob("*.md")))

    plugins_dir = config_root / "plugins"
    if plugins_dir.is_dir():
        for pdir in sorted(plugins_dir.iterdir()):
            if (pdir / "rules").is_dir():
                rule_files.extend(sorted((pdir / "rules").glob("*.md")))

    always_on_count = 0
    always_on_injected_chars = 0
    model_decision_count = 0
    other_lazy_count = 0

    for rf in rule_files:
        text = rf.read_text(encoding="utf-8", errors="replace")
        has_fm, body = _strip_frontmatter(text)
        fm = extract_frontmatter(text) if has_fm else {}
        base = rf.name
        is_special = base in ("AGENTS.md", "GEMINI.md")

        if is_special:
            trig = "always_on"
        elif not has_fm:
            errors.append(f"Rule {rf}: missing YAML frontmatter")
            trig = "always_on"
        else:
            trig = str(fm.get("trigger") or "always_on").strip()
            if trig not in VALID_RULE_TRIGGERS:
                errors.append(f"Rule {rf}: Invalid rule trigger '{trig}'")
            if trig == "model_decision" and not str(fm.get("description") or "").strip():
                errors.append(f"Rule {rf}: trigger 'model_decision' requires non-empty 'description:'")
            if trig == "glob" and not fm.get("globs"):
                errors.append(f"Rule {rf}: trigger 'glob' requires 'globs:'")

        if trig == "always_on" or is_always_on_rule(base, text):
            always_on_count += 1
            always_on_injected_chars += len(body.strip())
        elif trig == "model_decision":
            model_decision_count += 1
        else:
            other_lazy_count += 1

    if always_on_injected_chars > always_on_budget:
        errors.append(
            f"Always-on rule budget exceeded: {always_on_injected_chars} injected chars > {always_on_budget}"
        )

    return (
        {
            "total": len(rule_files),
            "always_on_count": always_on_count,
            "always_on_injected_chars": always_on_injected_chars,
            "always_on_budget": always_on_budget,
            "model_decision_count": model_decision_count,
            "other_lazy_count": other_lazy_count,
        },
        errors,
    )


def _check_skill_links(skill_file: Path, config_root: Path) -> list[str]:
    errs: list[str] = []
    text = skill_file.read_text(encoding="utf-8", errors="replace")
    fm = extract_frontmatter(text)
    if not str(fm.get("name") or "").strip():
        errs.append(f"Skill {skill_file}: missing frontmatter 'name'")
    if not str(fm.get("description") or "").strip():
        errs.append(f"Skill {skill_file}: missing frontmatter 'description'")

    skill_dir = skill_file.parent
    for link in _MD_LINK_RE.findall(text):
        if link.startswith(("http://", "https://", "mailto:", "#", "<", "customization://", "sidecar://")):
            continue
        if "<" in link or ">" in link:
            continue
        cand = (skill_dir / link).resolve()
        if not cand.exists():
            errs.append(f"Skill {skill_file}: broken relative link '{link}'")

    skills_root = config_root / "skills"
    for rel in _GLOBAL_SKILL_REF_RE.findall(text):
        cleaned = rel.rstrip(".,;:)`'\"")
        if "<" in cleaned or ">" in cleaned:
            continue
        cand = (skills_root / cleaned).resolve()
        if not cand.exists():
            errs.append(f"Skill {skill_file}: missing skill reference path '~/.gemini/config/skills/{cleaned}'")
    return errs


def _audit_skills_and_plugins(config_root: Path) -> tuple[dict[str, Any], list[str], dict[str, Path]]:
    errors: list[str] = []
    known_skills: dict[str, Path] = {}

    global_skills = config_root / "skills"
    if global_skills.is_dir():
        for sf in sorted(global_skills.glob("*/SKILL.md")):
            known_skills[sf.parent.name] = sf
            errors.extend(_check_skill_links(sf, config_root))

    plugin_count = 0
    plugins_dir = config_root / "plugins"
    if plugins_dir.is_dir():
        for pdir in sorted(plugins_dir.iterdir()):
            if not pdir.is_dir():
                continue
            for sf in sorted(pdir.glob("skills/*/SKILL.md")):
                known_skills[sf.parent.name] = sf
                errors.extend(_check_skill_links(sf, config_root))
            if (pdir / "plugin.json").is_file():
                plugin_count += 1
                ok, p_errs, _ = validate_plugin_surface(pdir)
                if not ok:
                    errors.extend(f"Plugin {pdir.name}: {e}" for e in p_errs)

    return {"total_skills": len(known_skills), "plugins_audited": plugin_count}, errors, known_skills


def _scan_transcripts(
    brain_root: Path,
    known_skills: dict[str, Path],
    days: int,
    min_repeat: int,
) -> tuple[dict[str, int], list[dict[str, Any]], int]:
    usage: Counter[str] = Counter()
    cli_errors: Counter[str] = Counter()
    cutoff = time.time() - days * 86400
    scanned_files = 0

    if not brain_root.is_dir():
        return {}, [], 0

    skill_names = sorted(known_skills.keys())
    for tpath in sorted(brain_root.glob("*/.system_generated/logs/transcript.jsonl")):
        try:
            if tpath.stat().st_mtime < cutoff:
                continue
        except OSError:
            continue
        scanned_files += 1
        try:
            with open(tpath, "r", encoding="utf-8", errors="replace") as fh:
                for raw in fh:
                    if "/SKILL.md" in raw:
                        try:
                            entry = json.loads(raw)
                        except json.JSONDecodeError:
                            entry = None
                        if isinstance(entry, dict):
                            for tc in entry.get("tool_calls", []) or []:
                                args = tc.get("args") or {}
                                pval = str(
                                    args.get("Path") or args.get("path") or args.get("file_path") or ""
                                )
                                for sname in skill_names:
                                    if f"/{sname}/SKILL.md" in pval:
                                        usage[sname] += 1
                    for err_m in _CLI_ERROR_RE.finditer(raw):
                        norm = " ".join(err_m.group(1).strip().split())
                        if norm:
                            cli_errors[norm] += 1
        except OSError:
            continue

    repeated = [
        {"pattern": pat, "count": cnt}
        for pat, cnt in sorted(cli_errors.items(), key=lambda kv: (-kv[1], kv[0]))
        if cnt >= min_repeat
    ]
    return dict(usage), repeated, scanned_files


def _query_denials(db_path: Path, days: int) -> dict[str, Any]:
    if not db_path.is_file():
        return {"total": 0, "by_tool": {}}
    cutoff = time.time() - days * 86400
    by_tool: Counter[str] = Counter()
    total = 0
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE type = 'PRIMARY_TOOL_DENIED' AND created_at >= ?",
                (cutoff,),
            ).fetchall()
            for (payload_raw,) in rows:
                total += 1
                tool = "unknown"
                try:
                    payload = json.loads(payload_raw or "{}")
                    if isinstance(payload, dict) and payload.get("tool"):
                        tool = str(payload["tool"])
                except json.JSONDecodeError:
                    pass
                by_tool[tool] += 1
    except sqlite3.Error:
        return {"total": 0, "by_tool": {}}
    return {"total": total, "by_tool": dict(by_tool)}


def run_weekly_audit(
    config_root: Optional[Path] = None,
    brain_root: Optional[Path] = None,
    db_path: Optional[Path] = None,
    days: int = 7,
    always_on_budget: int = 8000,
    min_repeat: int = 2,
) -> dict[str, Any]:
    cfg = (config_root or Path("~/.gemini/config").expanduser()).resolve()
    brain = (brain_root or Path("~/.gemini/antigravity/brain").expanduser()).resolve()
    db = (db_path or (cfg / "plugins" / "attention-guard" / "attention_guard.db")).resolve()

    rules_info, rule_errors = _audit_rules(cfg, always_on_budget=always_on_budget)
    skills_info, skill_errors, known_skills = _audit_skills_and_plugins(cfg)
    usage, repeated_cli_errors, transcripts_scanned = _scan_transcripts(brain, known_skills, days, min_repeat)
    unused_skills = sorted(name for name in known_skills if usage.get(name, 0) == 0)
    denials = _query_denials(db, days)

    all_errors = rule_errors + skill_errors
    return {
        "valid": len(all_errors) == 0,
        "errors": all_errors,
        "rules": rules_info,
        "skills": {
            **skills_info,
            "skill_usage": usage,
            "unused_skills": unused_skills,
        },
        "transcripts_scanned": transcripts_scanned,
        "repeated_cli_errors": repeated_cli_errors,
        "denials_7d": denials,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only Weekly Skills & Rules Health Audit CLI (REQ-048)")
    parser.add_argument("--config-root", type=Path, default=None)
    parser.add_argument("--brain-root", type=Path, default=None)
    parser.add_argument("--db-path", type=Path, default=None)
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--always-on-budget", type=int, default=8000)
    parser.add_argument("--min-repeat", type=int, default=2)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = run_weekly_audit(
        config_root=args.config_root,
        brain_root=args.brain_root,
        db_path=args.db_path,
        days=args.days,
        always_on_budget=args.always_on_budget,
        min_repeat=args.min_repeat,
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Weekly Audit valid={report['valid']} always_on={report['rules']['always_on_injected_chars']}"
            f"/{report['rules']['always_on_budget']} skills={report['skills']['total_skills']} "
            f"unused={len(report['skills']['unused_skills'])} repeated_cli={len(report['repeated_cli_errors'])} "
            f"errors={len(report['errors'])}"
        )
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
