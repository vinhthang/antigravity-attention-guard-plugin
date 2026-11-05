# Architectural Decision Records: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking, Watchdog Enforcement & Telemetry Alignment

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
  1. `RULE[agent-delegation]` instructs the Primary Agent to reuse existing idle subagents via `send_message` when continuing work. However, only `invoke_subagent` was wired to `inject-rules.py` and `record-tool-result.py`. Re-dispatching a subagent via `send_message` left its `work_items` row in `COMPLETED` under the old `parent_turn_id`, causing `attention-check.py` to see `active_work: false`, close the parent turn prematurely, and drop the subagent's `WORK_TERMINATED_OK` event on `Stop`.
  2. Even when `active_count > 0`, `attention-check.py` allowed Primary Agent `Stop` unconditionally (`elif active_count > 0: return emit({"decision": "allow"})`) without checking whether a 300s `schedule` watchdog timer had been armed since the last wakeup (`TimerCondition="any"` automatically cancels any prior timer when a `SYSTEM_MESSAGE` arrives).
- **Decision**:
  1. In `scripts/enforce-delegation.py` (`PreToolUse`, when `not is_sub` and `tool_name in ("send_message", "default_api:send_message")`) and `scripts/record-tool-result.py` (`PostToolUse`, `hooks.json` matcher `"invoke_subagent|send_message"`): when `Recipient` targets a subagent and `Message` is a valid JSON object, reactivate/upsert the subagent's `work_items` row (`status = 'ACTIVE'`, `parent_conv_id = conv_id`, `parent_turn_id = str(turn_id)`, `step_idx = str(step_idx)`) and emit `WORK_PREPARED` + `HANDOFF_ACCEPTED` events for `(conv_id, str(turn_id))`.
  2. In `scripts/common.py` (`is_subagent`), query `work_items` for the claimed token (or `claimed_by = conv_id`) so `parent_conv_id` and `parent_turn_id` reflect the latest re-dispatched turn, and only insert `WORK_CLAIMED` / `RUNNING` when `claim_token` newly transitions `claimed` from `0` to `1`.
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

---

## ADR-004: Content-Grounded Context Token Telemetry & SQLite `turns` Table Lifecycle (`REQ-031`)
- **Status**: Proposed
- **Addresses**: `REQ-031`
- **Context**:
  1. `attention-refresh.py` computed `total_tokens = os.path.getsize(transcript_path) // 4`. Because `transcript.jsonl` includes JSON serialization metadata, large internal `thinking` traces (which are not re-fed as active prompt context on subsequent turns), and historical pre-compaction steps, sessions quickly reported `85k`–`6.02M` tokens, overwriting `session_checkpoint.md` on every refresh and diverging up to 190x from `session_stats` (`total_session_chars`, which was only updated on `invoke_subagent` `PostToolUse`).
  2. The `turns` table in `attention_guard.db` remained completely empty (`0` rows across 448 closed turns) because no code path in `scripts/ledger.py` inserted or updated `turns`.
- **Decision**:
  1. In `parse_transcript(transcript_path)`, compute `active_context_chars` by summing `len(str(step.get("content") or ""))` plus `len(json.dumps(step.get("tool_calls")))` across valid JSON step objects, excluding `thinking` fields and resetting `active_context_chars = 0` when a compaction step (`type == "COMPACTION"` or `"compacted"` in `type.lower()`) is encountered. Track `has_valid_json_steps: bool`.
  2. In `scripts/attention-refresh.py`, when `has_valid_json_steps` is `True`, compute `total_tokens = parsed["active_context_chars"] // 4` and synchronize `session_stats` via `ledger.sync_session_chars(session_id, parsed["active_context_chars"])`. When `has_valid_json_steps` is `False` (e.g., synthetic raw-byte unit tests in `tests/test_attention_refresh.py` that write `"x" * 160000`), fall back to `os.path.getsize(transcript_path) // 4`.
  3. In `Ledger.insert_event()`, upsert `(f"{actor_id}_{turn_id}", status, now)` into `turns` when `WORK_PREPARED` (`EXECUTION_ACTIVE`), `STOP_REQUESTED` (`STOP_REQUESTED`), or `TURN_CLOSED` (`CLOSED`) events are recorded, and prune `CLOSED` turns older than `retention_seconds` in `Ledger.prune()`.
- **Trade-offs & Risks**:
  - *Trade-off*: Summing `content` and `tool_calls` in `parse_transcript()` adds a few string length operations during the single-pass transcript scan.
  - *Mitigation*: `parse_transcript()` already parses each line with `json.loads()` and caches results by `(st_mtime_ns, st_size)` in `_TRANSCRIPT_CACHE` (`REQ-018`), so computing `active_context_chars` during that single pass adds negligible overhead while eliminating the 190x telemetry inflation.
- **Rejected Alternatives**:
  - *Binding `record-tool-result.py` to `PostToolUse` `matcher: ".*"`*: Rejected because spawning a Python interpreter subprocess after every read-only tool call (`read_file`, `grep`, etc.) would add hook latency to every tool invocation, whereas `parse_transcript()` already runs in `PreInvocation` (`attention-refresh.py`).
  - *Dropping the `turns` table from `ledger.py`*: Rejected because keeping and populating `turns` provides a fast, direct summary of active vs. closed turns for `diagnostics.py` and `system_audit.py` without replaying all rows in `events`.

---

## ADR-005: Custom Rule File Autotrigger Fallback in `surface_validator.py` (`REQ-032`)
- **Status**: Proposed
- **Addresses**: `REQ-032`
- **Context**:
  `surface_validator.py` assumed every plugin places its skill routing triggers in `rules/AGENTS.md` (`surface.autotrigger_file`). Plugins that use a custom rule file name (such as `google-cloud-developer` with `rules/google-cloud-discovery.md`) failed `system_audit.py` when bundled skills were not explicitly named in `rules/*.md`, and `autotrigger()` attempted to create a separate `rules/AGENTS.md` instead of appending to the existing rule file.
- **Decision**:
  1. Update `autotrigger()` and `validate_plugin_surface(..., repair_triggers=True)` in `scripts/surface_validator.py` so that if `surface.autotrigger_file` is not in `tree`, it selects the first sorted `rules/*.md` file in `tree` as the target file for skill trigger injection.
  2. Run `surface_validator.py --autotrigger` (or add the 4 bundled skill trigger lines directly) on `/Users/thanghoang/.gemini/config/plugins/google-cloud-developer/rules/google-cloud-discovery.md` so `scripts/system_audit.py` passes with 0 errors.
- **Trade-offs & Risks**:
  - *Trade-off*: Modifying `~/.gemini/config/plugins/google-cloud-developer/rules/google-cloud-discovery.md` updates an installed marketplace plugin file on disk, which could be overwritten if the user reinstalls `google-cloud-developer`.
  - *Mitigation*: Because `surface_validator.py --autotrigger` now supports custom `rules/*.md` files, any future reinstall can be repaired automatically with a single `--autotrigger` invocation.
- **Rejected Alternatives**:
  - *Exempting `google-cloud-developer` by hardcoded name in `system_audit.py`*: Rejected because all installed plugins should satisfy uniform skill discoverability invariants without hardcoded exclusions.
