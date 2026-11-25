# Decisions: Weekly Skills & Rules Health Audit CLI

Governing specification: [spec.md](./spec.md)

## Architectural rationale

- Governs: `REQ-048`

Providing a single read-only CLI (`scripts/weekly_skill_rule_audit.py`) allows the Friday scheduled automation to audit all rules, skills, plugin surfaces, recent transcript CLI friction, and SQLite denial telemetry in one deterministic pass without mutating user configs or git checkouts.

## ADR-009: Bounded streaming scan over recent `transcript.jsonl` logs

- Governs: `REQ-048`
- State: Accepted
- Context and constraints: `~/.gemini/antigravity/brain/` grows across many conversations and multi-megabyte transcripts; scanning every historical file blindly wastes CPU and pulls fixed months-old CLI errors into weekly reports.
- Decision: Filter `<brain-root>/*/.system_generated/logs/transcript.jsonl` by `mtime >= now - days * 86400`, stream lines sequentially, extract `SKILL.md` `read_file` paths from tool call arguments, match normalized CLI flag/invocation error signatures (`unrecognized arguments`, `unknown flag`, `no such option`, `command not found`, `can't open file`), and report only patterns occurring `>= min_repeat` times.
- Affected components: `scripts/weekly_skill_rule_audit.py`, `tests/test_weekly_skill_rule_audit.py`.

## Gate 1: normative review

| Check | Status | Evidence / required correction |
| --- | --- | --- |
| Codebase grounding | PASS | Builds on `surface_validator.py` (`is_always_on_rule`, `VALID_RULE_TRIGGERS`) and `ledger.py` SQLite `events`. |
| Attributable intent and explicit scope | PASS | Implements user-confirmed #2 weekly read-only audit; non-goals exclude automated writes during cron. |
| Observable requirements and meaningful acceptance criteria | PASS | `AC-048-1` and `AC-048-2` define exact CLI inputs, JSON fields, time-window cutoff, repeat threshold, and exit codes. |
| Assumptions and owner-deferred questions are explicit | PASS | Missing transcript/SQLite paths degrade to empty metrics rather than crashing; zero `[PROVISIONAL]` items. |
| Architectural rationale respects requirements | PASS | `ADR-009` keeps weekly scans fast and noise-free (`--days`, `--min-repeat`). |
| IDs and references consistent | PASS | Allocates `REQ-048` and `ADR-009` cleanly above `REQ-047` / `ADR-008`. |
