# Verification: Weekly Skills & Rules Health Audit CLI

Governing specification: [spec.md](./spec.md)

## Planned checks

### AC-048-1 (REQ-048)

- Method: Run `pytest tests/test_weekly_skill_rule_audit.py` on a valid config root, plugins, SQLite denials ledger, and transcripts, verifying `valid: true`, exact `always_on_injected_chars`, `skill_usage` / `unused_skills`, `repeated_cli_errors: []`, and exit code `0`.
- Expected outcome: Audit reports clean health (`valid: true`, exit `0`) and accurate telemetry counts.

### AC-048-2 (REQ-048)

- Method: Run `pytest tests/test_weekly_skill_rule_audit.py` and `mutation_runner.py` (`>= 80%`) covering broken skill reference links, invalid rule `trigger`, `always_on` budget overflow, `--days` cutoff filtering, `--min-repeat` threshold filtering, and exit code `1`.
- Expected outcome: Structural/budget errors produce `valid: false` and exit `1`; `mutation_runner.py` achieves `>= 80%`.

## Execution evidence

### Run 1 — 2026-11-26

- Environment: macOS, Python `3.11`, Antigravity `2.4`.
- Result: PASS (`AC-048-1`..`AC-048-2` passed).
- Full test suite (`PYTHONPATH=scripts rtk test pytest tests/`): **`172 passed, 1 warning in 3.04s`** (`0` failed).
- Mutation audit (`mutation_runner.py --target-file scripts/weekly_skill_rule_audit.py --test-cmd "pytest -q tests/test_weekly_skill_rule_audit.py"`): **`80.0%` (`8/10` killed)**.
- Plugin surface & deploy (`surface_validator.py --json` & `deploy_plugin.py`): **`valid: true` (`always_on_chars: 3986 / 8000`)**, synced live to `~/.gemini/config/plugins/attention-guard`.
- Live dry-run audit (`weekly_skill_rule_audit.py --days 7 --json`): Scanned `234` recent transcripts (`31` skills, `30` active, `1` unused `use-yaak`, `6,989 / 8,000` `always_on` chars, `14` repeated CLI error signatures).

## Real-world observations

No real-world confirmation has been recorded.
