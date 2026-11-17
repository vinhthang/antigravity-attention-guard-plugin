# Verification: Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance

Governing specification: [spec.md](./spec.md)

## Planned checks

### AC-038-1 (REQ-038)

- Method: Unit tests in `tests/test_antigravity_v2_gemini4.py` testing `is_thinking_model()`, `resolve_context_budget()`, `attention-refresh.py::main()`, and `<CONTEXT_SUMMARY>` compaction reset in `parse_transcript()`.
- Expected outcome: `"Gemini 4 Argon (High)"` and `"Gemini 4 Carbon (High)"` return `True`; `attention-refresh` reports `1000k budget` (`400k` checkpoint) for Gemini models and preserves `128k` default when `modelName` is unset; `<CONTEXT_SUMMARY>` resets `active_context_chars`.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-038-2 (REQ-038)

- Method: Unit tests in `tests/test_antigravity_v2_gemini4.py` passing custom and malformed `ATTENTION_GUARD_THINKING_MODELS`, `AGY_TOKEN_BUDGET`, and `AGY_CHECKPOINT_THRESHOLD` env values.
- Expected outcome: Valid env overrides take precedence (scaling `threshold` by `0.625` when only `AGY_TOKEN_BUDGET` is overridden and clamping `threshold <= budget`); malformed/non-positive strings (`"invalid"`, `"0"`, `"-10"`) fall back cleanly to model defaults without raising exceptions.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-039-1 (REQ-039)

- Method: Hook integration tests in `tests/test_antigravity_v2_gemini4.py` exercising `inject-rules.py` on `swarm{action:"add"}`, `enforce-delegation.py` on `.py` mutations and `pytest` commands under `"Gemini 4 Carbon (High)"`, and `attention-refresh.py` inside native workers.
- Expected outcome: Author briefs receive `[AGY_SWARM_WORKER]` (`narrator`/`monitor` untouched, zero `work_items` rows added); native `swarm` and `run_workflow` workers receive `{"decision": "allow"}` on code edits and `pytest` runs; `attention-refresh.py` emits `{}`.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-039-2 (REQ-039)

- Method: Adversarial boundary tests in `tests/test_antigravity_v2_gemini4.py` testing a Swarm Coordinator whose `PLANNER_RESPONSE` and `GENERIC` (`read_board`) steps contain `[AGY_SWARM_WORKER]`, forged `[AGY_SWARM_WORKER]` normalization to `[AGY_SWARM_HELPER]` inside depth-1 workers, leaf helper `swarm(action="add")` denial, and native workers attempting `git reset --hard`, `assert True` test tampering, and 3x identical `run_command` loops.
- Expected outcome: `is_native_worker()` returns `False` for the Coordinator (denying direct `.py` edits and `pytest`), leaf helpers cannot spawn nested swarm workers, and native workers receive `{"decision": "deny"}` on destructive commands, test tampering, and doom loops.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-040-1 (REQ-040)

- Method: Transcript parser tests in `tests/test_antigravity_v2_gemini4.py` simulating `run_workflow` (`Description="Audit modules"` and unlabeled sync/async completions) alongside `run_command(IsDaemon=True)` in the same turn.
- Expected outcome: `has_delegation_in_turn` is `True`; `run_workflow`'s `task-N` enters `active_bg_tasks` while `run_command(IsDaemon=True)`'s `task-M` stays excluded from `active_bg_tasks`.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-040-2 (REQ-040)

- Method: Subagent recursion tests in `tests/test_antigravity_v2_gemini4.py` invoking `enforce-delegation.py` with `run_workflow`, `default_api:run_workflow`, `swarm`, and `default_api:swarm` inside both Executor (`may_delegate=False`) and Coordinator (`may_delegate=True, remaining_depth=1`) subagents.
- Expected outcome: All four tool calls return `{"decision": "deny"}`.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-041-1 (REQ-041)

- Method: Packaging tests plus CLI execution of `deploy_plugin.py --deploy`, `surface_validator.py`, `system_audit.py`, `agy plugin validate`, and `validate_specs.py`.
- Expected outcome: Zero legacy `Subagents=[` or `spec-gate.py` claims remain in `rules/AGENTS.md`, `templates/`, `skills/`, or `README.md`; `plugin.json` version is `"1.1.0"`; deployed `~/.gemini/config/plugins/attention-guard` matches repo and all CLI validators pass.
- Execution: [Run 1](#run-1--2026-11-18)

### AC-041-2 (REQ-041)

- Method: `surface_validator.py` and `tests/test_standalone_packaging.py` assertions on `rules/AGENTS.md` budget, skill triggers, and path portability.
- Expected outcome: `always_on_chars <= 8000`, both `attention-metrics` and `git-worktree-sandbox` triggers are present, and zero `/Users/thanghoang` paths exist across shipped files.
- Execution: [Run 1](#run-1--2026-11-18)

## Execution evidence

### Run 1 — 2026-11-18

- Scope: `AC-038-1`, `AC-038-2`, `AC-039-1`, `AC-039-2`, `AC-040-1`, `AC-040-2`, `AC-041-1`, `AC-041-2`
- Commands:
  - `PYTHONDONTWRITEBYTECODE=1 rtk pytest tests/` -> `261 passed in 4.51s`
  - `mutation_runner.py` -> `scripts/inject-rules.py` `100.0% (6/6)`, `scripts/attention-refresh.py` `100.0% (20/20)`, `scripts/common.py` `95.0% (19/20)`, `scripts/enforce-delegation.py` `95.0% (19/20)`
  - `rtk python3 scripts/deploy_plugin.py --deploy` -> `exit 0` (`~/.gemini/config/plugins/attention-guard` synced to `v1.1.0`; live `PreInvocation` refresh confirmed `1000k budget` on Gemini 4)
  - `rtk python3 scripts/surface_validator.py` -> `Plugin surface valid (2 skills, 7344/8000 always-on chars)`
  - `agy plugin validate` -> `Validation passed (skills 2, rules 1, hooks 2)`
  - `rtk python3 scripts/system_audit.py` -> `[PASS] attention-guard`, `[PASS] spec-driven-plugin`, SQLite ledger valid
- Result: `AC-038-1` PASS, `AC-038-2` PASS, `AC-039-1` PASS, `AC-039-2` PASS, `AC-040-1` PASS, `AC-040-2` PASS, `AC-041-1` PASS, `AC-041-2` PASS

## Real-world observations

No real-world confirmation has been recorded.
