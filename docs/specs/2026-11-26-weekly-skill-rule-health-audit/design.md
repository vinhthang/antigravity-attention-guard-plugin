# Design: Weekly Skills & Rules Health Audit CLI

Sources: [spec.md](./spec.md), [decisions.md](./decisions.md)

## Components

| Requirement / AC | Path and symbol | Responsibility / change |
| --- | --- | --- |
| REQ-048 / AC-048-1, AC-048-2 | `scripts/weekly_skill_rule_audit.py::run_weekly_audit`, `_audit_rules`, `_audit_skills`, `_scan_transcripts`, `_query_denials`, `main` | Audit global/plugin rule frontmatter & `always_on` budget, global/plugin skill frontmatter & links, plugin surfaces (`validate_plugin_surface`), recent `transcript.jsonl` skill usage & repeated CLI errors, and SQLite `PRIMARY_TOOL_DENIED` events; emit JSON or text report and return `0` / `1`. |
| REQ-048 / AC-048-1, AC-048-2 | `tests/test_weekly_skill_rule_audit.py` | Unit + CLI tests covering healthy audits, broken links, invalid rule triggers, budget overflow, `--days` window filtering, `--min-repeat` filtering, SQLite denials, and `--json` exit codes. |

## Interfaces and flow

1. `_audit_rules(config_root)` inspects `rules/*.md` and `plugins/*/rules/*.md` using `extract_frontmatter()` and `is_always_on_rule()`, validating `VALID_RULE_TRIGGERS` and summing `always_on_injected_chars` (body after frontmatter). Fails (`valid = False`) if `always_on_injected_chars > always_on_budget` or frontmatter is invalid.
2. `_audit_skills(config_root)` inspects `skills/*/SKILL.md` and `plugins/*/skills/*/SKILL.md` for `name`/`description` frontmatter and verifies every referenced `./references/...`, `./scripts/...`, and `~/.gemini/config/skills/...` path resolves on disk; also runs `validate_plugin_surface()` on plugin directories containing `plugin.json`.
3. `_scan_transcripts(brain_root, known_skills, days, min_repeat)` scans recent `transcript.jsonl` files (`mtime >= cutoff`), counting `SKILL.md` mentions in `read_file` calls and aggregating normalized CLI error signatures (`count >= min_repeat`).
4. `_query_denials(db_path, days)` queries `events` (`type = 'PRIMARY_TOOL_DENIED'` and `created_at >= cutoff`) when the SQLite file exists.

## Boundaries and recovery

- Absent `brain_root` or `attention_guard.db`: returns zero usage/denials without error.
- Re-links/symlinks to `~/.gemini/config/skills/<name>/...` in isolated temp-root tests resolve against `config_root / "skills"` so tests are hermetic without reading `~/.gemini`.
