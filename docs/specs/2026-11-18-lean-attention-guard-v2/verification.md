# Verification: Lean Attention Guard v2.0.0

Governing specification: [spec.md](./spec.md)

## Planned checks

### AC-042-1 (REQ-042)

- Method: Unit tests in `tests/test_lean_v2_architecture.py` inspecting `hooks.json`, deleted file paths, and `enforce-delegation.py` responses on Primary Agent `.py` writes and `rtk pytest` runs under `"Gemini 4 Carbon (High)"` and `"Claude Opus 4.6"`.
- Expected outcome: `hooks.json` contains only `PreToolUse`; retired scripts and `schemas/` do not exist; Primary Agent code edits and test runs return `{"decision": "allow"}`.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-042-2 (REQ-042)

- Method: Unit tests in `tests/test_enforce_delegation.py` and `tests/test_lean_v2_architecture.py` testing destructive commands (`git reset --hard`, `git clean -fd`, `rm -rf /`) and test tampering (`@pytest.mark.skip`, `assert True`) across Primary and Subagent callers.
- Expected outcome: Returns `{"decision": "deny"}` and inserts `PRIMARY_TOOL_DENIED` with `{"tool": tool_name, "is_sub": bool, "reason": str}`.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-043-1 (REQ-043)

- Method: Unit and benchmark tests in `tests/test_lean_v2_architecture.py` testing `inject-rules.py` `Model` preservation (`"inherit"`, `"flash"`, omitted), in-process `O(1)` timing, and `subprocess.run(["python3", "scripts/enforce-delegation.py"])` wall-clock median against a `3.2 MB` synthetic Primary Agent `transcript.jsonl`.
- Expected outcome: `Model` is never silently rewritten; subagent tokens are detected across `USER_INPUT` and `SYSTEM_MESSAGE` headers; in-process `O(1)` evaluation completes in `< 5 ms` and subprocess wall-clock median completes in `< 100 ms` on a `3.2 MB` transcript.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-043-2 (REQ-043)

- Method: Unit test in `tests/test_lean_v2_architecture.py` where the Primary Agent's own transcript contains `[ANTIGRAVITY_TOKEN:<uuid>]` inside its `PLANNER_RESPONSE` tool call (`conv_id == parent_conv_id`).
- Expected outcome: `is_subagent()` returns `is_sub is False` and does not claim the child's token.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-044-1 (REQ-044)

- Method: Hook integration tests in `tests/test_lean_v2_architecture.py` and `tests/test_e2e_hook_pipeline.py` testing Executor `send_message` with plain Markdown and JSON summaries, no `verify_cmd` `shell=True` execution, and `DeepCoder` Coordinator (`remaining_depth=1`) leaf delegation.
- Expected outcome: Concise Markdown and JSON `send_message` payloads return `{"decision": "allow"}` without executing shell commands; Coordinator can spawn leaf Executors (`remaining_depth=0`).
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-044-2 (REQ-044)

- Method: Adversarial tests in `tests/test_lean_v2_architecture.py` and `tests/test_enforce_delegation.py` testing Executor `invoke_subagent`/`run_workflow`/`swarm`, 3x identical polling `run_command` doom loop, active `task-*` background process on `send_message`, and ANSI/traceback raw log dumps.
- Expected outcome: All four cases return `{"decision": "deny"}`, and doom-loop trips record `BREAKER_STATE_CHANGE`.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-045-1 (REQ-045)

- Method: Database migration and metrics tests in `tests/test_lean_v2_architecture.py`, `tests/test_ledger_performance.py`, and `tests/test_sync_metrics.py` testing fresh DB creation, `SCHEMA_VERSION = 2` -> `3` migration, `diagnostics.py --metrics --json`, and `sync_metrics.py`.
- Expected outcome: Existing v2 DBs migrate cleanly without data loss; `diagnostics.py --metrics --json` reports `PRIMARY_TOOL_DENIED`, `primary_denials`, `subagent_denials`, and `denials_by_tool`; `sync_metrics.py` tests pass.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-045-2 (REQ-045)

- Method: CLI tests in `tests/test_lean_v2_architecture.py` running `diagnostics.py --metrics --json` and `sync_metrics.py` against an empty `AGY_APP_DATA_DIR`.
- Expected outcome: Both exit `0` cleanly without raising unhandled exceptions.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-046-1 (REQ-046)

- Method: Run `deploy_plugin.py --deploy`, `surface_validator.py`, `agy plugin validate`, and packaging assertions in `tests/test_standalone_packaging.py` and `tests/test_lean_v2_architecture.py`.
- Expected outcome: `rules/AGENTS.md` is `<= 4,000` chars with both skill triggers and zero retired ceremony strings; `~/.gemini/config/plugins/attention-guard` has retired scripts and `schemas/` pruned; all validators exit `0`.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

### AC-046-2 (REQ-046)

- Method: Unit tests in `tests/test_surface_validator.py` and `tests/test_deploy_plugin.py` passing missing hook scripts or missing skill triggers.
- Expected outcome: `surface_validator.py` and `deploy_plugin.py` reject invalid bundles before modifying the target directory.
- Execution: PASS in [Run 1](#run-1--2026-11-18).

## Execution evidence

### Run 1 — 2026-11-18

- Environment: macOS, Python `3.11`, Antigravity `2.0` (`agy plugin validate`).
- Result: PASS (`AC-042-1`..`AC-046-2` passed).
- Automated test suite (`PYTHONDONTWRITEBYTECODE=1 rtk pytest -p no:cacheprovider tests/ -q`): **`117 passed in 1.76s`** (`0` failed) covering `AC-042-1`..`AC-046-2`.
- Latency benchmark (`3.11 MB` live `transcript.jsonl` + `3.2 MB` synthetic `transcript.jsonl`):
  - In-process `O(1)` `enforce-delegation.main()` evaluation: **`< 1.0 ms`** (`< 5.0 ms` bound).
  - Subprocess `enforce-delegation.py` wall-clock median (5 live `.pyc`-cached runs): **`40.2 ms`** (`39.5 ms`–`44.7 ms`, down from `159.3 ms` in `v1.1.0`; `0 ms` on `read_file` / `PreInvocation` / `PostToolUse` / `Stop`).
- Mutation testing (`mutation_runner.py`):
  - `scripts/common.py`: **`100.0%` (`20/20` killed)**.
  - `scripts/ledger.py`: **`100.0%` (`18/18` killed)**.
  - `scripts/inject-rules.py`: **`100.0%` (`4/4` killed)**.
  - `scripts/enforce-delegation.py`: **`95.0%` (`19/20` killed)**.
- Deployment, surface & CLI validation:
  - `rtk python3 scripts/deploy_plugin.py --deploy`: **`Deployment completed successfully`** (`~/.gemini/config/plugins/attention-guard` pruned of retired scripts and `schemas/`).
  - `rtk python3 scripts/surface_validator.py`: **`Plugin surface valid (2 skills, 3362/8000 always-on chars)`** (down from `7,344` chars).
  - `agy plugin validate`: **`Validation passed (skills 2 · rules 1 · hooks 1)`**.
  - `prepare_code_review.py` + `rtk git diff --check HEAD`: **`Approved` (`0` `P0`/`P1` defects, `0` whitespace warnings)** after remediating inline `-c`/`-e` script path extraction in `scripts/system_audit.py`.

## Real-world observations

- 2026-11-18: Deployed `attention-guard` `v2.0.0` live in active Antigravity session `3ce7b6fa-a5ef-4c38-b727-3852c9f01757`; Primary Agent executed direct `.py` edits and `rtk pytest` runs without Thinking-Mode blocks or `Stop`-hook rejections while `PreToolUse` safety hooks remained active. Pending explicit human confirmation before transitioning to `Verified`.
