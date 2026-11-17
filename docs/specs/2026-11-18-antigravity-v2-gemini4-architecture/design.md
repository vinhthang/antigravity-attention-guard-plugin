# Design: Antigravity 2.0 orchestration, Gemini 4 detection, and native worker governance

Sources: [spec.md](./spec.md), [decisions.md](./decisions.md)

## Components

| Requirement / AC | Path and symbol | Responsibility / change |
| --- | --- | --- |
| REQ-038 / AC-038-1, AC-038-2 | `scripts/common.py::DEFAULT_THINKING_MODELS`, `resolve_context_budget`, `parse_transcript`; `scripts/attention-refresh.py::PRIMARY_RULES_REMINDER`, `main` | Add `"argon"` and `"carbon"` to `DEFAULT_THINKING_MODELS`; add `resolve_context_budget(model_name)` returning `(1_000_000, 400_000)` for Gemini, `(200_000, 140_000)` for Claude, `(128_000, 80_000)` default with env overrides; reset `active_context_chars` on `<context_summary>`. |
| REQ-039 / AC-039-1, AC-039-2 | `scripts/common.py::is_native_worker`; `hooks.json`; `scripts/inject-rules.py::main`; `scripts/enforce-delegation.py::main`; `scripts/attention-refresh.py::main` | Match `"invoke_subagent|swarm"` in `hooks.json`; tag `swarm(action="add")` author briefs with `[AGY_SWARM_WORKER]`; detect native `swarm` and `run_workflow` workers via `is_native_worker()` to allow code/test execution under Gemini 4 while preserving safety guards. |
| REQ-040 / AC-040-1, AC-040-2 | `scripts/enforce-delegation.py::main`; `scripts/common.py::parse_transcript` | Deny `run_workflow` and `swarm` inside `invoke_subagent` subagents (`is_sub == True`); match `run_workflow` (`Description`) independently from `run_command` (`toolSummary`/`CommandLine`) when popping `planner_tool_calls` for backgrounded `task-N` steps. |
| REQ-041 / AC-041-1, AC-041-2 | `rules/AGENTS.md`, `templates/{EXECUTOR,COORDINATOR}.md`, `skills/git-worktree-sandbox/SKILL.md`, `plugin.json`, `README.md`, `scripts/deploy_plugin.py` | Replace legacy `Subagents=[...]` and `spec-gate.py` docs with Antigravity 2.0 `Workspace="share|branch"`, `run_workflow`, `swarm`, and `spec-driven` `v3.x`; bump version to `"1.1.0"` and deploy to `~/.gemini/config/plugins/attention-guard`. |

## Interfaces and flow

- `resolve_context_budget(model_name: str = "") -> tuple[int, int]`: Maps `"gemini" | "argon" | "carbon"` -> `(1_000_000, 400_000)`, `"opus" | "sonnet" | "claude"` -> `(200_000, 140_000)`, and empty/other -> `(128_000, 80_000)`, then applies `AGY_TOKEN_BUDGET` and `AGY_CHECKPOINT_THRESHOLD` positive-int overrides (scaling `threshold` by `0.625` when only `AGY_TOKEN_BUDGET` is overridden, and clamping `threshold <= budget`). `attention-refresh.py::main()` passes `resolve_context_budget(get_primary_model(data))` to `build_refresh_reminder()`.
- `is_native_worker(data: dict, parsed: dict | None = None) -> bool` and `is_leaf_native_worker(data: dict, parsed: dict | None = None) -> bool`: Return `True` on explicit positive worker payload fields (`swarmMember`, `isSwarmWorker`, `workflowId`, `isWorkflowAgent`) OR dedicated prompt tags (`<swarm_worker>`, trailing `[AGY_SWARM_WORKER]` / `[AGY_SWARM_HELPER]` line, or leading `[AGY_WORKFLOW_WORKER]` prefix) in `USER_INPUT`/`SYSTEM_MESSAGE` steps—ignoring inter-agent `sender=`/`[Message] timestamp=` wakeup envelopes, resetting on human `<USER_REQUEST>` steps (and unmarked `USER_EXPLICIT` human prompts while still recognizing step-1 worker briefs delivered as `USER_EXPLICIT` without `<USER_REQUEST>`), and resetting on orchestrator `invoke_subagent` / `run_workflow` / `swarm(action="title")` calls. `is_leaf_native_worker()` identifies leaf `[AGY_SWARM_HELPER]` and workflow (`[AGY_WORKFLOW_WORKER]` / `workflowId` / `isWorkflowAgent`) workers.
- `inject-rules.py` (`swarm` branch): When `toolCall.name in ("swarm", "default_api:swarm")` and normalized `action == "add"`, if `name` is not `"narrator"`/`"monitor"` (or `narrator-*`/`monitor-*`) and `brief` is a non-empty string lacking a trailing `[AGY_SWARM_WORKER]`/`[AGY_SWARM_HELPER]` line, emits `{"decision": "allow", "overwrite": {**args, "brief": f"{brief}\n{tag}"}}` (using `[AGY_SWARM_HELPER]` when called by an existing native swarm worker and `[AGY_SWARM_WORKER]` from the Coordinator) without inserting `tokens` or `work_items` rows.
- `enforce-delegation.py` (`is_native_worker` branch): Denies `manage_subagents`, `invoke_subagent`, `run_workflow`, coordinator-only `swarm(action="title")`, and `swarm(action="add")` inside leaf `[AGY_SWARM_HELPER]` or workflow workers (capping native swarm fan-out to one helper tier); permits `send_message` with test/build `verify_cmd` (`ctx["is_sub"] = True`) without creating Primary-Agent `work_items` rows; and enforces `check_destructive_command()`, `check_test_tampering()`, `check_subagent_doom_loop()`, and `record_subagent_file_edit()` before exempting the worker from Primary-Agent-only thinking-mode / plan-active blocks.

## Boundaries and recovery

- Malformed `AGY_TOKEN_BUDGET` / `AGY_CHECKPOINT_THRESHOLD` env values (`"abc"`, `"-5"`, `"0"`) fall back cleanly to model-derived defaults without raising `ValueError`.
- Coordinator and inbox safety: `is_native_worker()` ignores `GENERIC` tool outputs (`read_board`), `PLANNER_RESPONSE` tool arguments (`swarm{action:"add"}`), and subagent `sender=` `<SYSTEM_MESSAGE>` replies mentioning worker tags, so the Primary Agent and Swarm Coordinator never self-unlock.
- Async workflow task isolation: `_pop_matching_planner_call()` restricts shell exit completions (`Command exited with code`) to `run_command` and prefers unlabeled fallback entries before labeled ones so an unlabeled `run_command(IsDaemon=True)` never steals a labeled `run_workflow(Description=...)` entry or vice versa.

## Dependencies and unresolved design work

None.
