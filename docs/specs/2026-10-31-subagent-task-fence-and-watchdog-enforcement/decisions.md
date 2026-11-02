# Architectural Decision Records: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking & Watchdog Enforcement

## ADR-001: Transcript-Grounded Background Task Fence on Subagent `send_message` (`REQ-027`)
- **Status**: Proposed
- **Addresses**: `REQ-027`
- **Context**:
  Subagents executing long-running remote commands via `run_command` (`WaitMsBeforeAsync` exceeded -> `Tool is running as a background task with task id: <conv_id>/task-<N>`) must yield their turn and wait for a `SYSTEM` `SYSTEM_MESSAGE` notification before reporting completion. During the Oct 31 fleet `dnf update`, the `flash` executor subagent hallucinated `<system_message>...Task id ".../task-282" finished...</system_message>` inside its own `MODEL` `PLANNER_RESPONSE` text, cancelled its internal timers, and called `send_message(status="completed")` to the Primary Agent while `task-282` and `task-288` were still running. This left the subagent stuck in `waiting_for_dependents` for over an hour.
- **Decision**:
  1. Extend `parse_transcript(transcript_path)` in `scripts/common.py` to parse and return `active_bg_tasks: list[str]`. A task is added when a `GENERIC` step reports `Tool is running as a background task with task id: <task_id>` with a `Task Description:` that is not `Timer:` / `Cron:` and whose corresponding `run_command` tool call did not specify `IsDaemon: true`. A task is removed **only** when a `SYSTEM` `SYSTEM_MESSAGE` step (`source == "SYSTEM"`) reports completion/cancellation for `<task_id>` (`sender=<task_id>` or `Task id "<task_id>" (finished|was canceled|was cancelled)`) or a `GENERIC` step reports `Task "<task_id>" cancel(l)?ed.`.
  2. In `scripts/enforce-delegation.py`, intercept `send_message` / `default_api:send_message` when `is_sub == True`. If `parsed["active_bg_tasks"]` is non-empty, return `{"decision": "deny", "reason": "..."}` listing the still-running task IDs.
  3. Update `rules/EXECUTOR.md` to forbid fabricating `<system_message>` blocks or calling `send_message` while background command tasks remain active.
- **Trade-offs & Risks**:
  - *Trade-off*: A subagent cannot send intermediate progress messages via `send_message` while a non-daemon background `run_command` task is still running. In Antigravity's execution model, executor subagents only call `send_message` once upon terminal completion or failure (`schemas/executor-payload.json`), so blocking `send_message` while non-daemon background tasks are in flight aligns with the executor contract.
  - *Risk*: Standing background processes (`IsDaemon: true`) could block `send_message` if not excluded. We mitigate this by checking `IsDaemon` on the preceding `PLANNER_RESPONSE` `run_command` tool call and excluding daemon tasks from `active_bg_tasks`.
- **Rejected Alternatives**:
  - *Relying solely on prompt instructions in `rules/EXECUTOR.md`*: Rejected because LLM subagents under `flash` can still hallucinate `<system_message>` tags under high context pressure without a deterministic `PreToolUse` hook gate.
  - *Checking `manage_task(Action="list")` via subprocess inside the hook*: Rejected because hooks do not have access to the runtime's internal task manager RPC; `transcript.jsonl` is the single deterministic source of truth available to hooks.

---

## ADR-002: `send_message` Subagent Re-Dispatch Ledger Activation & Wakeup-Scoped Watchdog Gate on `Stop` (`REQ-028`)
- **Status**: Proposed
- **Addresses**: `REQ-028`
- **Context**:
  1. `RULE[agent-delegation]` instructs the Primary Agent to reuse existing idle subagents via `send_message` when continuing work. However, only `invoke_subagent` was wired to `inject-rules.py` and `record-tool-result.py`. Re-dispatching a subagent via `send_message` left its `work_items` row in `COMPLETED` under the old `parent_turn_id`, causing `attention-check.py` to see `active_count == 0` and `is_subagent()` to return the stale `parent_turn_id`.
  2. Even when `active_count > 0`, `attention-check.py` allowed Primary Agent `Stop` unconditionally (`elif active_count > 0: return emit({"decision": "allow"})`) without checking whether a 300s `schedule` watchdog timer had been armed since the last wakeup (`TimerCondition="any"` automatically cancels any prior timer when a `SYSTEM_MESSAGE` arrives).
- **Decision**:
  1. In `scripts/enforce-delegation.py` (`PreToolUse`, when `not is_sub` and `tool_name in ("send_message", "default_api:send_message")`) and `scripts/record-tool-result.py` (`PostToolUse`, `hooks.json` matcher `"invoke_subagent|send_message"`): when `Recipient` targets a subagent and `Message` is a valid JSON object, reactivate/upsert the subagent's `work_items` row (`status = 'ACTIVE'`, `parent_conv_id = conv_id`, `parent_turn_id = str(turn_id)`, `step_idx = str(step_idx)`) and emit `WORK_PREPARED` + `HANDOFF_ACCEPTED` events for `(conv_id, str(turn_id))`.
  2. In `scripts/common.py` (`is_subagent`), query `work_items` for the claimed token (or `claimed_by = conv_id`) so `parent_conv_id` and `parent_turn_id` reflect the latest re-dispatched turn.
  3. Extend `parse_transcript(transcript_path)` to compute `active_timers_since_wakeup: list[str]`. Any `USER_INPUT` or `SYSTEM` `SYSTEM_MESSAGE` step clears timers from earlier wake cycles (matching `TimerCondition="any"` semantics). A subsequent `GENERIC` step with `Task Description: Timer:...` (or a `PLANNER_RESPONSE` step with a `schedule` tool call when `GENERIC` is not yet written) adds an active timer unless cancelled by a later `GENERIC` `Task "<id>" cancelled.` step.
  4. In `scripts/attention-check.py`, when `not is_sub` and (`active_count > 0` or `len(active_bg_tasks) > 0`), verify `len(active_timers_since_wakeup) > 0` (when `os.environ.get("AGY_REQUIRE_WATCHDOG_ON_STOP", "1") != "0"` and the transcript contains at least one tool-call or background-task step in the current turn). If no watchdog timer is active, return `{"decision": "continue", "reason": "..."}` up to `MAX_STOP_REJECTIONS`.
- **Trade-offs & Risks**:
  - *Trade-off*: Synthetic unit tests that manually insert `ACTIVE` `work_items` into SQLite without writing a `schedule` step into `transcript.jsonl` could trigger the watchdog gate if not scoped carefully.
  - *Mitigation*: Enforce the watchdog gate when `active_bg_tasks` is non-empty in the transcript OR when the transcript's current turn contains an `invoke_subagent` / `send_message` `PLANNER_RESPONSE` tool call (or `AGY_FORCE_WATCHDOG_CHECK == "1"`), preserving backward compatibility with bare SQLite unit fixtures that do not write tool calls to `transcript.jsonl`.
- **Rejected Alternatives**:
  - *Spawning a background timer automatically from inside `attention-check.py`*: Rejected because `Stop` hooks cannot invoke Antigravity runtime tools (`schedule`); they must return `{"decision": "continue", "reason": "..."}` so the Primary Agent calls `schedule`.

---

## ADR-003: Lexical `~/.gemini/` Exclusion in `spec-gate.py` `extract_prompt_workspaces()` (`REQ-029`)
- **Status**: Proposed
- **Addresses**: `REQ-029`
- **Context**:
  `extract_prompt_workspaces()` in `spec-gate.py` resolved every `/...` regex match via `Path(p_str).resolve()` before checking if it belonged to a repository with `docs/specs/INDEX.md`. Because `~/.gemini/config/plugins/attention-guard` is a symlink to `/Users/thanghoang/github/antigravity-attention-guard-plugin`, referencing `/Users/thanghoang/.gemini/config/plugins/attention-guard/schemas/executor-payload.json` in a subagent prompt caused `spec-gate.py` to require an active `In-Progress` specification in `antigravity-attention-guard-plugin` even when the subagent was working exclusively in `/Users/thanghoang/github/oci`.
- **Decision**:
  In `extract_prompt_workspaces()`, strip trailing punctuation (`.,;:)'"`), expand user home (`~`), and skip any path match whose lexical (un-resolved) path contains `/.gemini/` or starts with `str(Path.home() / ".gemini")`.
- **Trade-offs & Risks**:
  - *Trade-off*: If a developer tries to mutate a plugin repo strictly through its `~/.gemini/config/plugins/<name>` symlink path inside a subagent prompt without mentioning `/Users/thanghoang/github/<repo>`, `extract_prompt_workspaces` will ignore the `~/.gemini/` path and fall back to `candidate_workspaces`.
  - *Mitigation*: Direct file mutations (`edit_file`, `write_file`) still resolve symlinks via `resolve_target_workspace(target_file.resolve(), candidate_workspaces)`, so actual edits to plugin files remain gated by `spec-gate.py`.
- **Rejected Alternatives**:
  - *Allowing `invoke_subagent` if ANY workspace in `mentioned_workspaces` has a valid spec*: Rejected because a single subagent prompt genuinely mutating two target repositories should still verify specifications across actual target repositories.
