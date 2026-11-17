# Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance

- Feature ID: 2026-11-18-antigravity-v2-gemini4-architecture
- Type: enhancement
- Status: In-Testing
- First entered In-Testing: 2026-11-18
- Related specifications: Proposed: Changes [2026-10-31-subagent-task-fence-and-watchdog-enforcement](../2026-10-31-subagent-task-fence-and-watchdog-enforcement/spec.md), [2026-11-05-standalone-marketplace-packaging](../2026-11-05-standalone-marketplace-packaging/spec.md)

## Problem and source intent

User request: "this need to address the new architecture of antigravity and gemini 4" (selecting dual-plugin upgrade for `spec-driven-plugin` v3.2.0 and `antigravity-attention-guard-plugin` v1.1.0, and approving `implementation_plan.md`).

Grounding against Antigravity 2.0's built-in skills (`antigravity_guide`, `run-workflow`, `native_swarm`, `swarm_monitor`) and live `transcript.jsonl` logs exposed four concrete architectural gaps in `antigravity-attention-guard-plugin`:
1. `scripts/common.py::DEFAULT_THINKING_MODELS` (`["opus", "gemini-4", "gemini 4"]`) misses Gemini 4 internal codename identifiers (`"argon"`, `"carbon"`), and `scripts/attention-refresh.py` hardcodes a legacy `128k`/`80k` token budget despite Gemini 4 operating on a `1M` context window (`~519k` pre-compaction tokens observed in live `CHECKPOINT` steps).
2. Native `swarm` workers (`swarm{action:"add"}`, omitting `model` per `swarm` contract) and `run_workflow` `agent(..., model="inherit")` workers run in separate conversations without `[ANTIGRAVITY_TOKEN:...]`. Under Gemini 4, `is_subagent()` returns `False`, causing `scripts/enforce-delegation.py` to misclassify them as the user-facing Primary Agent and block all code edits and test executions.
3. Unprivileged `invoke_subagent` subagents (`is_sub == True`) are blocked from `invoke_subagent`/`manage_subagents` (`enforce-delegation.py:847`) but can still call `run_workflow` or `swarm`, bypassing recursion depth limits; meanwhile, `common.py::parse_transcript` assumes every non-Timer/Cron background `task-N` came from `run_command`, risking mis-popping a sibling `run_command(IsDaemon=True)` when `run_workflow` backgrounds.
4. `rules/AGENTS.md`, `templates/{EXECUTOR,COORDINATOR}.md`, `skills/git-worktree-sandbox/SKILL.md`, and `README.md` still instruct legacy `Subagents=[worker1, worker2]` syntax and retired `spec-driven-plugin` v1.x hooks instead of Antigravity 2.0 flat `invoke_subagent(..., Workspace="share|branch")`, `run_workflow`, `swarm`, and `spec-driven` v3.x.

## Repository grounding

Baseline (`v1.0.0`) symbols inspected prior to `v1.1.0` changes:
- `scripts/common.py`: `DEFAULT_THINKING_MODELS`, `is_thinking_model()`, `parse_transcript()`, and `is_subagent()` (extended in `v1.1.0` with `resolve_context_budget()`, `_pop_matching_planner_call()`, and `is_native_worker()`).
- `scripts/enforce-delegation.py`: Primary Agent thinking-mode and plan-active guards in `main()`, plus subagent recursion, doom-loop, destructive-command, test-tampering, and task-fence checks.
- `scripts/inject-rules.py` & `hooks.json`: `PreToolUse` rule/token injection hook (widened in `v1.1.0` from `"invoke_subagent"` to `"invoke_subagent|swarm"`).
- `scripts/attention-refresh.py`: `PRIMARY_RULES_REMINDER`, `build_refresh_reminder()` (default `token_budget=128000`, `checkpoint_threshold=80000` when `modelName` is unset), and `main()`.
- `scripts/deploy_plugin.py`: Synchronizes repository files to the live installed copy at `~/.gemini/config/plugins/attention-guard`.
- Baseline test suite: `tests/` (`214` passing tests across 16 test modules prior to adding `tests/test_antigravity_v2_gemini4.py`).

## Non-goals

- Adding SQLite `work_items` / `walkthrough.md` Stop-hook blocking to native `swarm` board turns (swarm workers coordinate via `post_message`/`read_board`/`swarm_wait`, not `invoke_subagent` tokens).
- Modifying `attention-metrics-server` HTTP endpoints or dashboard UI.

## Requirements

### REQ-038: Gemini 4 codename detection and model-aware context window telemetry

- Source intent: User request ("this need to address the new architecture of antigravity and gemini 4") and observed `128k` vs `1M` compaction telemetry mismatch.
- Statement: WHEN `is_thinking_model()`, `resolve_context_budget()`, and `parse_transcript()` evaluate model names and session transcripts, THE plugin SHALL classify Gemini 4 `Argon`/`Carbon` identifiers as thinking models, resolve `(1_000_000, 400_000)` context/checkpoint budgets for Gemini models (`(200_000, 140_000)` for Claude models, honoring `AGY_TOKEN_BUDGET` and `AGY_CHECKPOINT_THRESHOLD` overrides), and reset `active_context_chars` across both `CHECKPOINT`/`COMPACTION` and `<CONTEXT_SUMMARY>` compaction boundaries.
- AC-038-1 — Success: `is_thinking_model()` returns `True` for `"Gemini 4 Argon (High)"`, `"Gemini 4 Carbon (High)"`, `"gemini-4-argon"`, and `"carbon-thinking"`, and `attention-refresh.py::main()` renders `1000k budget` (with `400,000` checkpoint threshold) when `modelName` is a Gemini model while keeping `build_refresh_reminder()`'s default `token_budget=128000` when `modelName` is omitted.
- AC-038-2 — Boundary/failure: IF `ATTENTION_GUARD_THINKING_MODELS` or `AGY_TOKEN_BUDGET` / `AGY_CHECKPOINT_THRESHOLD` is set (including malformed non-integer env values), THEN `is_thinking_model()` and `resolve_context_budget()` SHALL honor valid overrides and fall back deterministically without raising exceptions on malformed env strings.

### REQ-039: Native `swarm` and `run_workflow` worker recognition under thinking models

- Source intent: Grounding discovery that Antigravity 2.0 `swarm` workers (inheriting Gemini 4) and `run_workflow` `agent()` workers lack `[ANTIGRAVITY_TOKEN:...]` and deadlock on `enforce-delegation.py:803`.
- Statement: WHEN a conversation executes as an Antigravity 2.0 native `swarm` worker or `run_workflow` `agent()` worker, THE plugin SHALL recognize it via `is_native_worker()` (and lightweight `[AGY_SWARM_WORKER]` tagging on `swarm{action:"add"}` briefs) so code edits and test/build commands are permitted under thinking models while destructive-command, test-tampering, and doom-loop guards remain enforced and Primary Agent refresh reminders are suppressed.
- AC-039-1 — Success: `inject-rules.py` (matched via `hooks.json` `"invoke_subagent|swarm"`) appends `[AGY_SWARM_WORKER]` to `swarm{action:"add"}` briefs (excluding `narrator`/`monitor` roles) without creating `work_items` rows, and `enforce-delegation.py` allows `write_file`/`edit_file` on `.py` files and `pytest` runs when `is_native_worker()` is `True` under `"Gemini 4 Carbon (High)"` while `attention-refresh.py` emits `{}`.
- AC-039-2 — Boundary/failure: IF a Swarm Coordinator's own transcript contains `[AGY_SWARM_WORKER]` only inside its `PLANNER_RESPONSE` `swarm{action:"add"}` tool call or `GENERIC` `read_board` output (or if a native worker executes `git reset --hard`, tampers with test assertions, or hits the 3x identical `run_command` doom loop), THEN `is_native_worker()` SHALL return `False` for the Coordinator and `enforce-delegation.py` SHALL still deny the Coordinator's direct code edits as well as any native worker's destructive, test-tampering, or doom-loop tool calls.

### REQ-040: Subagent recursion fence for `run_workflow`/`swarm` and async workflow task matching

- Source intent: User request to align hook governance with Antigravity 2.0's `run_workflow` and `swarm` orchestration tools.
- Statement: WHEN an `invoke_subagent` subagent (`is_sub == True`) attempts to call `run_workflow` or `swarm`, THE `enforce-delegation.py` hook SHALL deny the call; and WHEN the Primary Agent backgrounds a `run_workflow` task alongside `run_command` calls, THE `parse_transcript()` parser SHALL match `run_workflow` (`Description`) and `run_command` (`toolSummary`/`CommandLine`) independently when tracking `active_bg_tasks` and `has_delegation_in_turn`.
- AC-040-1 — Success: `parse_transcript()` sets `has_delegation_in_turn = True` on `run_workflow`/`swarm` calls and tracks a backgrounded `run_workflow` task in `active_bg_tasks` without popping a sibling `run_command(IsDaemon=True)` entry from `planner_tool_calls`.
- AC-040-2 — Boundary/failure: IF any `invoke_subagent` child (`is_sub == True`, including a Coordinator with `may_delegate == True`) invokes `run_workflow`, `default_api:run_workflow`, `swarm`, or `default_api:swarm`, THEN `enforce-delegation.py` SHALL return `{"decision": "deny"}` preventing unbounded multi-agent recursion.

### REQ-041: Antigravity 2.0 governance rules, templates, worktree skill, documentation, and live deployment

- Source intent: User request ("this need to address the new architecture of antigravity and gemini 4") covering flat `invoke_subagent` `Workspace` modes, `run_workflow`/`swarm` selection rules, `README.md`, and live plugin sync.
- Statement: WHEN `attention-guard` `v1.1.0` is packaged and deployed, THE plugin's `rules/AGENTS.md`, `templates/{EXECUTOR,COORDINATOR}.md`, `skills/git-worktree-sandbox/SKILL.md`, `plugin.json`, and `README.md` SHALL document Antigravity 2.0 flat `invoke_subagent(..., Workspace="inherit|share|branch")`, `run_workflow`, `swarm`, and `spec-driven-plugin` `v3.x` within the `8,000`-character always-on budget and synchronize cleanly to `~/.gemini/config/plugins/attention-guard`.
- AC-041-1 — Success: Zero `Subagents=[` legacy instructions or retired `spec-gate.py` claims remain in `rules/AGENTS.md`, `templates/`, `skills/`, or `README.md`; `plugin.json` version is `"1.1.0"`; and `deploy_plugin.py --deploy`, `surface_validator.py`, `system_audit.py`, and `agy plugin validate` exit `0`.
- AC-041-2 — Boundary/failure: IF `rules/AGENTS.md` exceeds `8,000` characters, omits a bundled skill trigger (`attention-metrics`, `git-worktree-sandbox`), or contains `/Users/thanghoang` paths, THEN `surface_validator.py` and `tests/test_standalone_packaging.py` SHALL fail validation.

## Assumptions and owner-deferred questions

- Reversible assumption: Defaulting unknown/unset `modelName` in `resolve_context_budget("")` to `(128_000, 80_000)` preserves 100% compatibility with existing unit tests while applying `(1_000_000, 400_000)` automatically whenever Antigravity passes a Gemini model name.

## Approvals and lifecycle history

- 2026-11-18 (`Planning -> In-Progress`): User approved `implementation_plan.md` covering `REQ-038`..`REQ-041`; Gate 1 and Gate 2 passed.
- 2026-11-18 (`In-Progress -> In-Testing`): Tasks 1 and 2 completed (`261/261` unit tests, `95%`–`100%` mutation kill rates, `v1.1.0` deployed live); recorded [Run 1](./verification.md#run-1--2026-11-18).
