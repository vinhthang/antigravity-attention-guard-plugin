# Lean Attention Guard v2.0.0: fast O(1) mechanical safety rails and zero-ceremony governance

- Feature ID: 2026-11-18-lean-attention-guard-v2
- Type: enhancement
- Status: In-Testing
- First entered In-Testing: 2026-11-18
- Related specifications: Implemented: Replaces [2026-11-18-antigravity-v2-gemini4-architecture](../2026-11-18-antigravity-v2-gemini4-architecture/spec.md)

## Problem and source intent

User request: "`/plan` `/grill-me` go with design a Lean v2" (following the empirical SQLite ledger audit showing that 4 mechanical safety guards delivered 100% of real catches across 2,953 events while Thinking-Mode Primary blocks, `Stop`/`PreInvocation`/`PostToolUse` hooks, 300s `schedule` watchdogs, `walkthrough.md` `mtime` gates, UUID JSON schemas, and full-transcript parsing on `matcher: ".*"` added ~160 ms/call latency and 55% false-friction denials).

Confirmed `/grill-me` decisions (`Q1`–`Q6`):
1. **Advisory Primary delegation, hard safety blocks only**: Unblock Primary Agent direct code edits, `rtk` tests/builds, and git operations; hard-block only destructive commands, test tampering, subagent recursion, doom loops, and raw log dumps.
2. **Remove `Stop` hook rejections**: Delete `attention-check.py` and `fsm.py` (relying on Antigravity 2.0 native reactive wakeup and normal `walkthrough.md` completion guidelines).
3. **Lightweight subagent handoffs**: Keep `[ANTIGRAVITY_TOKEN]` and raw-log-dump / active-bg-task fences on subagent `send_message`, while deleting UUID JSON schemas (`schemas/*.json`), `payload_validator.py`, and `subprocess.run(verify_cmd, shell=True)`.
4. **Remove `PreInvocation` and `PostToolUse` hooks**: Delete `attention-refresh.py` and `record-tool-result.py` (relying on native `<user_rules>` and `<CONTEXT_SUMMARY>` compaction).
5. **Respect explicit/default `Model`**: Stop silently rewriting `Model="inherit"` to `"flash"` in `inject-rules.py`.
6. **Slim SQLite ledger (`tokens` + `events`)**: Migrate `attention_guard.db` to `SCHEMA_VERSION = 3` (`tokens` + `events`), fix `PRIMARY_TOOL_DENIED` `{"tool", "is_sub", "reason"}` payloads, and preserve `attention-metrics` + `sync_metrics.py` compatibility with `attention-metrics-server`.

## Repository grounding

- `hooks.json` & `scripts/`: Currently `4,925` lines across 15 scripts running `PreToolUse` (`.*` and `invoke_subagent|swarm`), `PostToolUse`, `Stop`, and `PreInvocation`.
- `scripts/common.py::is_subagent`: Calls `parse_transcript()` across the entire `transcript.jsonl` (`159.3 ms` per `PreToolUse` subprocess on a `2.83 MB` transcript).
- `scripts/enforce-delegation.py::emit_deny`: Emits `PRIMARY_TOOL_DENIED` with `{"reason": reason}`, omitting `tool` expected by `attention-metrics-server/backend/main.go:119`.
- `scripts/deploy_plugin.py`: `BUNDLE_ITEMS` currently requires `schemas` and does not prune retired `scripts/*.py` files from `~/.gemini/config/plugins/attention-guard`.

## Non-goals

- Modifying `attention-metrics-server` Go backend or frontend endpoints.
- Blocking Primary Agent file edits, test runs, or git operations in `PreToolUse`.

## Requirements

### REQ-042: Scoped `PreToolUse`-only hook topology and Primary Agent autonomy

- Source intent: `/grill-me` Q1, Q2, and Q4 selections ("Advisory delegation, hard safety blocks only", "Remove Stop-hook rejections completely", "Remove both PreInvocation and PostToolUse").
- Statement: WHEN `attention-guard` `v2.0.0` is loaded, `hooks.json` SHALL register `PreToolUse` hooks strictly on mutating, shell, and delegation tools (`enforce-delegation.py` and `inject-rules.py` on `invoke_subagent` only) with zero `PreInvocation`, `PostToolUse`, or `Stop` hooks; and WHEN a non-subagent conversation (Primary Agent, native `swarm` worker, or `run_workflow` worker) invokes safe file mutations, test/build commands, or git commands, `enforce-delegation.py` SHALL allow them without Thinking-Mode or plan-state denials.
- AC-042-1 — Success: `hooks.json` defines only `PreToolUse` (omitting `read_file` from `matcher` and omitting `PreInvocation`, `PostToolUse`, and `Stop`); retired scripts (`attention-check.py`, `attention-refresh.py`, `record-tool-result.py`, `fsm.py`, `payload_validator.py`) and `schemas/` are absent; and `enforce-delegation.py` returns `{"decision": "allow"}` for Primary Agent `.py` edits and `rtk pytest` runs under Gemini 4 / Opus.
- AC-042-2 — Boundary/failure: IF any agent (Primary or Subagent) invokes a sweeping destructive command (`git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, unleased `git push --force`, catastrophic `rm -rf`) or introduces test-tampering markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `t.Skip(`, `assert True`), THEN `enforce-delegation.py` SHALL return `{"decision": "deny"}` and record `PRIMARY_TOOL_DENIED` with `{"tool": tool_name, "is_sub": is_sub, "reason": reason}`.

### REQ-043: Fast `O(1)` subagent token detection and model-preserving rule injection

- Source intent: `/grill-me` Q3 and Q5 selections ("Keep lightweight subagent marker", "Respect explicit/default Model (no silent hook override)") and `159 ms` `transcript.jsonl` latency audit.
- Statement: WHEN `inject-rules.py` intercepts `invoke_subagent`, IT SHALL record `(token_id, may_delegate, remaining_depth, parent_conv_id)` in `tokens`, offload prompts `> 12,000` characters via `materialize_context_pointer()`, and prepend `[ANTIGRAVITY_TOKEN:<uuid>]` + concise role rules + `EVIDENCE_BOUNDARY` without altering `Model`; and WHEN `is_subagent()` evaluates a tool call, IT SHALL resolve subagent status via SQLite `tokens.claimed_by` cache or the first `10` lines of `transcript.jsonl` without scanning full multi-megabyte transcripts.
- AC-043-1 — Success: `inject-rules.py` preserves `Model="inherit"` (and omitted or explicit `Model` values) verbatim while issuing `[ANTIGRAVITY_TOKEN:<uuid>]`; `is_subagent()` identifies subagents across `USER_INPUT` and `SYSTEM_MESSAGE` headers; and `enforce-delegation.py` completes in `< 5 ms` in-process (`O(1)`) and `< 100 ms` subprocess wall-clock time against a `3 MB` Primary Agent `transcript.jsonl`.
- AC-043-2 — Boundary/failure: IF a Primary Agent's own transcript contains `[ANTIGRAVITY_TOKEN:...]` inside its `PLANNER_RESPONSE` `invoke_subagent` tool call (`conv_id == parent_conv_id`), THEN `is_subagent()` SHALL return `(False, False, 0, None)` and never misclassify the Primary Agent as its own child.

### REQ-044: Subagent recursion cap, doom-loop circuit breaker, and `send_message` hygiene

- Source intent: `/grill-me` Q1 and Q3 selections preserving the 10-hit recursion cap, 4-hit doom-loop breaker, background-task fence, and raw-log-dump blocker while dropping UUID JSON schemas and `shell=True` `verify_cmd`.
- Statement: WHILE `is_sub == True`, `enforce-delegation.py` SHALL deny `run_workflow` and `swarm`, deny `invoke_subagent`/`manage_subagents` when `not may_delegate or remaining_depth <= 0`, trip the doom-loop circuit breaker on $\ge 3$ consecutive identical normalized `run_command` signatures without an intervening file edit (logging `BREAKER_STATE_CHANGE`), and allow concise Markdown or JSON `send_message` payloads while denying `send_message` when non-daemon background tasks remain active or `validate_no_raw_log_dump()` detects ANSI escapes, $\ge 4$-frame tracebacks, or `> 2,000`-char raw `pytest` dumps.
- AC-044-1 — Success: Executor subagents (`may_delegate=False`) can send concise plain-text/Markdown or JSON `send_message` replies without UUID fields and without `shell=True` `verify_cmd` execution, while Coordinator subagents (`TypeName="DeepCoder"`, `remaining_depth=1`) may invoke leaf `invoke_subagent` workers (`remaining_depth=0`) once.
- AC-044-2 — Boundary/failure: IF an Executor subagent invokes `invoke_subagent`/`run_workflow`/`swarm`, repeats an identical polling/failing command $3\times$ without editing a file, calls `send_message` with an active `task-*` background process, or dumps raw ANSI/traceback logs in `send_message`, THEN `enforce-delegation.py` SHALL return `{"decision": "deny"}`.

### REQ-045: Slim SQLite `SCHEMA_VERSION = 3` ledger and `attention-metrics-server` compatibility

- Source intent: `/grill-me` Q6 selection ("Slim SQLite ledger (`tokens` + `events` only)... keep `attention-metrics` + `sync_metrics.py` compatible with `attention-metrics-server`").
- Statement: WHEN `Ledger` initializes a new or existing `attention_guard.db`, IT SHALL create or non-destructively migrate `tokens` (including `may_delegate`, `remaining_depth`, `parent_conv_id`) and `events` at `SCHEMA_VERSION = 3`, prune events/tokens older than retention TTL opportunistically, and support `diagnostics.py --metrics --json` and `sync_metrics.py` batch syncing.
- AC-045-1 — Success: Opening both a fresh DB and a legacy `SCHEMA_VERSION = 2` DB succeeds without data loss; `diagnostics.py --metrics --json` outputs valid JSON including `PRIMARY_TOOL_DENIED`, `primary_denials`, `subagent_denials`, and `denials_by_tool`; and `sync_metrics.py` syncs `events` cleanly.
- AC-045-2 — Boundary/failure: IF `attention_guard.db` does not exist when `diagnostics.py --metrics --json` or `sync_metrics.py` runs, THEN both scripts SHALL exit `0` cleanly without creating corrupt files or raising unhandled exceptions.

### REQ-046: Lean `rules/AGENTS.md`, clean live deployment pruning, and surface compliance

- Source intent: `/grill-me` Q1–Q5 selections and `deploy_plugin.py` stale-artifact audit.
- Statement: WHEN `attention-guard` `v2.0.0` is packaged and deployed via `deploy_plugin.py --deploy`, `rules/AGENTS.md` (`<= 4,000` chars), `templates/{EXECUTOR,COORDINATOR}.md`, `plugin.json` (`"2.0.0"`), and `README.md` SHALL reflect Lean v2 governance without `schedule(300s)` or `payload_validator.py` instructions, and `deploy_plugin.py --deploy` SHALL prune retired scripts and `schemas/` from `~/.gemini/config/plugins/attention-guard`.
- AC-046-1 — Success: `rules/AGENTS.md` is `<= 4,000` characters, triggers `attention-metrics` and `git-worktree-sandbox`, and contains zero `payload_validator.py`, `DurationSeconds=300`, or `/Users/thanghoang` strings; `deploy_plugin.py --deploy` removes stale `v1.x` scripts/`schemas/` from `~/.gemini/config/plugins/attention-guard`; and `surface_validator.py`, `system_audit.py` (plugin + ledger check), and `agy plugin validate` pass.
- AC-046-2 — Boundary/failure: IF `hooks.json` references a deleted script or `rules/AGENTS.md` drops a bundled skill trigger, THEN `surface_validator.py` and `deploy_plugin.py` SHALL fail pre-flight verification before modifying the target installation directory.

## Assumptions and owner-deferred questions

- Reversible assumption: Retaining legacy tables (`work_items`, `turns`, `session_stats`) untouched if already present in an existing user `attention_guard.db` (while no longer creating or querying them in `v2.0.0`) avoids destructive `DROP TABLE` locks during live sessions.

## Approvals and lifecycle history

- 2026-11-18 (`Planning -> In-Progress`): Completed 6-question `/grill-me` design interview and received explicit user approval on `implementation_plan.md` for Lean `v2.0.0`.
- 2026-11-18 (`In-Progress -> In-Testing`): Tasks 1 and 2 completed (`117/117` tests, `95%`–`100%` mutation kill rates, `40.2 ms` cached subprocess latency on `3.11 MB` transcript, `v2.0.0` deployed live); recorded [Run 1](./verification.md#run-1--2026-11-18).
