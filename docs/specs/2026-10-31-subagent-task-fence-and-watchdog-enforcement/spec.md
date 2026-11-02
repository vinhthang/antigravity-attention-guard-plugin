# Specification: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking & Watchdog Enforcement

**Feature ID**: `2026-10-31-subagent-task-fence-and-watchdog-enforcement`  
**Status**: `planning`  
**Created**: `2026-10-31`  
**Version**: `1.0.0`  
**Sign-off**: `Pending User Approval`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Overview & Root Cause Summary

During the Oct 31 OCI `arm10` scaling and fleet-wide `dnf update` operations (`conversationId: 39e408bd-c43e-4cb9-ae48-188163e9b12b`, executor subagent `b9ffd136-e386-495a-9c41-dcab32ab85df`), three enforcement and lifecycle defects were uncovered across `antigravity-attention-guard-plugin` and `spec-driven-plugin`:

1. **Defect 1 — Subagent Premature `send_message` Completion While Background Tasks Remain `RUNNING` (`waiting_for_dependents`) (`REQ-027`)**:
   - In `b9ffd136-e386-495a-9c41-dcab32ab85df`'s transcript, `run_command` backgrounded `task-276` (`amd10`), `task-282` (`amd11`), and `task-288` (`gce10`). Instead of ending its turn to wait for genuine `SYSTEM` `<SYSTEM_MESSAGE>` task completion events, the `flash` model hallucinated `<system_message>...Task id ".../task-282" finished...</system_message>` inside its own `MODEL` `PLANNER_RESPONSE` text (`step_index` 279, 285, 291), killed its internal timer tasks (`task-278`, `task-284`, `task-290`), and called `send_message` (`status: "completed"`) to the Primary Agent while `task-282` and `task-288` were still running.
   - Because `task-282` and `task-288` remained active in the subagent's task queue, the subagent process stayed stuck in `waiting_for_dependents` (`Waiting for background tasks`) for over an hour after reporting completion.
2. **Defect 2 — Missing `send_message` Subagent Re-Dispatch Ledger Tracking & Unenforced 300s Watchdog on Primary Agent `Stop` (`REQ-028`)**:
   - When the Primary Agent re-used an existing idle subagent (`b9ffd136-e386-495a-9c41-dcab32ab85df`) via `send_message(Recipient="b9ffd136-...", Message="{...}")` in turns `236`, `272`, and `300`, `inject-rules.py` (`matcher: "invoke_subagent"`) did not run. Consequently, no `work_items` entry was marked `ACTIVE` for the new parent turn, `is_subagent()` continued returning the original `parent_turn_id = '80'` from Oct 25, and the parent turn's FSM remained in `State.OPEN`.
   - Furthermore, on Primary Agent `Stop` (`attention-check.py`), when `active_count > 0` (active subagents in `work_items`) or uncompleted non-daemon background `run_command` tasks exist in the Primary Agent's transcript, `attention-check.py` unconditionally returned `{"decision": "allow"}` without verifying that a `schedule` watchdog timer (`Timer:`) had been armed since the last wakeup (`USER_INPUT` or `SYSTEM_MESSAGE`).
3. **Defect 3 — False-Positive `spec-gate.py` Rejection When Subagent Prompts Reference `~/.gemini/` Plugin Symlinks (`REQ-029`)**:
   - In `spec-gate.py` (`extract_prompt_workspaces`), every `/...` path in the `invoke_subagent` prompt is passed through `Path(p_str).resolve()` and checked for `docs/specs/INDEX.md`. Because `RULE[agent-delegation]` requires prompts to reference `/Users/thanghoang/.gemini/config/plugins/attention-guard/schemas/executor-payload.json`, and `~/.gemini/config/plugins/attention-guard` is a symlink to `/Users/thanghoang/github/antigravity-attention-guard-plugin` (where all specs in `docs/specs/INDEX.md` had status `completed`), `extract_prompt_workspaces` added `antigravity-attention-guard-plugin` to `mentioned_workspaces` alongside `/Users/thanghoang/github/oci` and rejected `invoke_subagent` (`No active specification found in docs/specs/INDEX.md`).

---

## 2. Normative Requirements (EARS Syntax)

### `REQ-027` — Subagent Background Task Fence on `send_message` & Synthetic System-Message Prevention
- **WHEN** a subagent (`is_sub == True`) invokes `send_message` (`send_message` or `default_api:send_message`), **THE** `enforce-delegation.py` hook **SHALL** inspect the subagent's parsed transcript (`parse_transcript`) for uncompleted, non-daemon background `run_command` tasks (`active_bg_tasks`) and **SHALL** deny `send_message` if any background command task has not yet received a genuine `SYSTEM` `SYSTEM_MESSAGE` completion/cancellation event or an explicit `GENERIC` `Task "<id>" cancelled.` event.
- **Acceptance Criteria**:
  - `parse_transcript(transcript_path)` in `scripts/common.py` extracts `active_bg_tasks: list[str]` containing task IDs spawned by `GENERIC` steps (`Tool is running as a background task with task id: <id>`) whose `Task Description:` does not start with `Timer:` or `Cron:` and whose originating `run_command` tool call did not set `IsDaemon: true`.
  - A task ID in `active_bg_tasks` is removed **only** when a step with `source == "SYSTEM"` and `type == "SYSTEM_MESSAGE"` contains `sender=<task_id>` or `Task id "<task_id>" (finished|was canceled|was cancelled)`, or when a `GENERIC` step contains `Task "<task_id>" cancel(l)?ed.`.
  - Synthetic `<system_message>` text emitted inside a `MODEL` `PLANNER_RESPONSE` step does **not** clear `active_bg_tasks`.
  - Calling `send_message` from a subagent while `active_bg_tasks` is non-empty returns `{"decision": "deny", "reason": "..."}` listing the active task IDs and instructing the subagent to wait for `<SYSTEM_MESSAGE>` completion or call `manage_task(Action="kill", TaskId=...)`.
  - `rules/EXECUTOR.md` explicitly prohibits fabricating `<system_message>` tags or calling `send_message` while background command tasks (`task-*`) remain running.

### `REQ-028` — Subagent `send_message` Re-Dispatch Tracking & Primary Agent Watchdog Gate on `Stop`
- **WHEN** the Primary Agent (`is_sub == False`) dispatches work to a subagent via `send_message` (`Recipient` matching a subagent conversation ID and `Message` containing a valid JSON handoff payload), **THE** plugin **SHALL** reactivate/upsert the subagent's `work_items` record (`status = 'ACTIVE'`) for the current `(parent_conv_id, parent_turn_id)` and transition the turn FSM to `State.EXECUTION_ACTIVE`; and **WHEN** the Primary Agent attempts to stop its turn (`attention-check.py`) while in-flight subagent work (`active_count > 0`) or uncompleted Primary Agent background command tasks (`active_bg_tasks`) exist without an active `schedule` timer (`active_timers_since_wakeup`), **THE** `attention-check.py` hook **SHALL** return `{"decision": "continue", "reason": "..."}` requiring the Primary Agent to arm a 300s `schedule` watchdog timer.
- **Acceptance Criteria**:
  - Primary Agent `send_message` (`PreToolUse` in `enforce-delegation.py` and `PostToolUse` in `record-tool-result.py` via `hooks.json` matcher `"invoke_subagent|send_message"`) updates/inserts the recipient subagent's `work_items` row to `status = 'ACTIVE'`, `parent_conv_id = conv_id`, `parent_turn_id = str(turn_id)`, `step_idx = str(step_idx)` and records `WORK_PREPARED` and `HANDOFF_ACCEPTED` events for `(conv_id, str(turn_id))`.
  - `is_subagent()` in `scripts/common.py` resolves `parent_conv_id` and `parent_turn_id` from the subagent's `work_items` record when available so subsequent subagent `Stop` events update the re-dispatched parent turn rather than the historical initial turn.
  - `parse_transcript(transcript_path)` tracks `active_timers_since_wakeup: list[str]`, adding timer IDs when a `GENERIC` step spawns `Task Description: Timer:...` (or a `PLANNER_RESPONSE` step invokes `schedule` / `default_api:schedule`), removing them when explicitly cancelled (`Task "<id>" cancelled.`), and resetting prior wakeup timers whenever a new `USER_INPUT` or `SYSTEM` `SYSTEM_MESSAGE` step arrives.
  - On Primary Agent `Stop` (`attention-check.py`), if `active_count > 0` or `len(active_bg_tasks) > 0`, and `len(active_timers_since_wakeup) == 0` (unless `AGY_REQUIRE_WATCHDOG_ON_STOP == "0"`), `attention-check.py` returns `{"decision": "continue", "reason": "..."}` (bounded by `MAX_STOP_REJECTIONS`) instructing the Primary Agent to arm `schedule(DurationSeconds=300, TimerCondition="any")` or terminate hung subagents/tasks.

### `REQ-029` — Exclude `~/.gemini/` Plugin Symlink Paths in `spec-gate.py` Prompt Workspace Extraction
- **WHEN** `extract_prompt_workspaces()` in `/Users/thanghoang/.gemini/config/plugins/spec-driven-plugin/scripts/spec-gate.py` scans `invoke_subagent` prompt text for file paths, **THE** function **SHALL** ignore paths whose lexical (pre-symlink-resolution) path resides under `~/.gemini/` (such as `~/.gemini/config/plugins/.../schemas/executor-payload.json`) and strip trailing punctuation before path resolution so read-only plugin references do not resolve via symlinks into plugin development repositories and trigger false-positive spec-gate rejections.
- **Acceptance Criteria**:
  - An `invoke_subagent` prompt targeting `/Users/thanghoang/github/oci` (which has an active `In-Progress` specification) while referencing `/Users/thanghoang/.gemini/config/plugins/attention-guard/schemas/executor-payload.json` and `payload_validator.py` extracts only `/Users/thanghoang/github/oci` in `mentioned_workspaces` and returns `{"decision": "allow"}`.
  - An `invoke_subagent` prompt that lexically targets `/Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/enforce-delegation.py` directly still resolves `/Users/thanghoang/github/antigravity-attention-guard-plugin` and enforces `verify_active_specification()`.
