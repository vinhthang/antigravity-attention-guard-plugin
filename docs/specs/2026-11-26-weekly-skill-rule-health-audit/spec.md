# Weekly Skills & Rules Health Audit CLI (`weekly_skill_rule_audit.py`)

- Feature ID: 2026-11-26-weekly-skill-rule-health-audit
- Type: enhancement
- Status: In-Testing
- First entered In-Testing: 2026-11-26
- Related specifications: Extends [2026-11-18-lean-attention-guard-v2](../2026-11-18-lean-attention-guard-v2/spec.md)

## Problem and source intent

Customizations (`rules/*.md` and `skills/*/SKILL.md`) silently accumulate broken reference links, stale CLI flags, invalid frontmatter, and unused `always_on` bloat over time unless audited periodically against live transcripts and `attention_guard.db` denial telemetry.

## Repository grounding

- [scripts/surface_validator.py](../../../scripts/surface_validator.py): Validates plugin structure, skill triggers, and rule frontmatter per plugin directory.
- [scripts/system_audit.py](../../../scripts/system_audit.py): Audits ecosystem hooks, plugins, and SQLite ledger health.
- `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl`: Records `read_file` activations and shell/CLI stderr errors across recent turns.

## Non-goals

- Modifying `~/.gemini/config/rules/`, skills, or git repositories automatically during the scheduled weekly cron run (the cron stays strictly read-only and outputs proposed diffs).

## Requirements

### REQ-048: Read-only Weekly Skills & Rules Health Audit CLI (`weekly_skill_rule_audit.py`)

- Source intent: User requested #1 (inline `SKILL.md` auto-heal during live sessions) and #2 (scheduled weekly read-only audit across all rules, skills, recent transcripts, and denial telemetry).
- Statement: WHEN invoked via `weekly_skill_rule_audit.py [--config-root <dir>] [--brain-root <dir>] [--db-path <db>] [--days 7] [--always-on-budget 8000] [--min-repeat 2] [--json]`, the CLI SHALL inspect global and plugin rules, global and plugin skills, recent transcripts within `--days`, and SQLite `PRIMARY_TOOL_DENIED` events; verify valid YAML frontmatter, `always_on_injected_chars <= always-on-budget`, and existing relative/skill file links; aggregate skill `read_file` usage (`skill_usage`, `unused_skills`) and repeated CLI errors (`count >= min_repeat`); and exit `0` when structurally valid (`valid: true`) or `1` when structural/budget errors are detected (`valid: false`).
- AC-048-1 — Success: Against a healthy config root, transcripts, and ledger, `weekly_skill_rule_audit.py --json` exits `0`, returns `valid: true`, computes exact `always_on_injected_chars`, reports active vs `unused_skills`, surfaces `denials_7d`, and returns `repeated_cli_errors: []`.
- AC-048-2 — Boundary/failure: Broken `references/...` / `scripts/...` / `~/.gemini/config/skills/...` links, invalid rule `trigger` values, `always_on` budget overflow (`> --always-on-budget`), and `>= 2` repeated CLI flag errors in recent transcripts (ignoring transcripts older than `--days` and single 1-off errors `< 2`) mark structural failures with `valid: false` (exit `1`) and report only recurring CLI errors (`count >= min_repeat`).
