# Technical Design: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking & Watchdog Enforcement

## 1. Architectural Mapping to Requirements

| Component | File(s) | Requirement IDs |
|---|---|---|
| Transcript Task & Timer Parser (`active_bg_tasks`, `active_timers_since_wakeup`) | `scripts/common.py` | `Addresses: REQ-027, REQ-028` |
| Subagent `send_message` Background Task Fence & Executor Rules | `scripts/enforce-delegation.py`, `rules/EXECUTOR.md` | `Addresses: REQ-027` |
| Primary Agent `send_message` Re-Dispatch Ledger Activation & `is_subagent()` Turn Resolution | `scripts/enforce-delegation.py`, `scripts/record-tool-result.py`, `scripts/common.py`, `hooks.json` | `Addresses: REQ-028` |
| Primary Agent `Stop` Watchdog Timer Verification | `scripts/attention-check.py` | `Addresses: REQ-028` |
| Lexical `~/.gemini/` Symlink Exclusion in Prompt Workspace Extraction | `/Users/thanghoang/.gemini/config/plugins/spec-driven-plugin/scripts/spec-gate.py` | `Addresses: REQ-029` |

---

## 2. Detailed Component Design

### 2.1 Transcript Task & Timer Tracking in `parse_transcript()` (`REQ-027`, `REQ-028`)

1. **Extend `parse_transcript(transcript_path: str) -> dict` in `scripts/common.py`**:
   - Add two keys to the returned dictionary:
     - `"active_bg_tasks": list[str]` — ordered list of uncompleted, non-daemon background `run_command` task IDs (`<conv_id>/task-<N>`).
     - `"active_timers_since_wakeup": list[str]` — ordered list of active `schedule` timer task IDs (`<conv_id>/task-<N>` or synthetic `schedule-step-<idx>`) spawned since the last `USER_INPUT` or `SYSTEM` `SYSTEM_MESSAGE` step.
     - `"has_delegation_in_turn": bool` — `True` if any `PLANNER_RESPONSE` step in the current turn invoked `invoke_subagent`, `default_api:invoke_subagent`, `send_message`, or `default_api:send_message`.
   - **Step-by-step state transitions while iterating `steps`**:
     - Track `last_planner_had_daemon_cmd = False` and `current_turn_delegated = False`.
     - When `source.startswith("USER") and stype == "USER_INPUT"`:
       - Reset `current_turn_delegated = False` and clear `active_timers_since_wakeup.clear()`.
     - When `source == "SYSTEM" and stype == "SYSTEM_MESSAGE"`:
       - Clear `active_timers_since_wakeup.clear()` (since `TimerCondition="any"` cancels prior timers on wakeup, and if the message itself is a timer firing, that timer has now fired).
       - Inspect `content`:
         - Match `r'\bsender=([0-9a-fA-F\-]{36}/task-\d+)\b'` and `r'Task id "([^"]+/task-\d+)"\s+(?:finished|was cancel+ed)'`.
         - Remove any matched `task_id` from `active_bg_tasks`.
     - When `stype == "PLANNER_RESPONSE"`:
       - Inspect `step.get("tool_calls") or []`:
         - Set `last_planner_had_daemon_cmd = any(tc.get("name") in ("run_command", "default_api:run_command") and bool((tc.get("args") or {}).get("IsDaemon")) for tc in tool_calls if isinstance(tc, dict))`.
         - If any `tc.get("name") in ("invoke_subagent", "default_api:invoke_subagent", "send_message", "default_api:send_message")`:
           - Set `current_turn_delegated = True`.
         - If any `tc.get("name") in ("schedule", "default_api:schedule")`:
           - Add `f"schedule_call_{step.get('step_index', idx)}"` to `active_timers_since_wakeup` if not present.
     - When `stype == "GENERIC"`:
       - Inspect `content`:
         - Match `r'Tool is running as a background task with task id:\s*(\S+)'`:
           - Extract `task_id = m.group(1).strip()`.
           - Extract `Task Description:\s*(.*)` line (`desc`).
           - If `desc.startswith("Timer:")` or `desc.startswith("Cron:")`:
             - Add `task_id` to `active_timers_since_wakeup`.
           - Else if not `last_planner_had_daemon_cmd`:
             - Add `task_id` to `active_bg_tasks`.
         - Match `r'Task "([^"]+)" cancel+ed\.'`:
           - Extract `cancelled_id = m_cancel.group(1).strip()`.
           - Remove `cancelled_id` from `active_bg_tasks` and `active_timers_since_wakeup`.
           - If `cancelled_id` is removed from `active_timers_since_wakeup`, also remove the most recent `schedule_call_*` placeholder so an explicitly killed timer is not counted as active.

### 2.2 Subagent Background Task Fence in `enforce-delegation.py` & `rules/EXECUTOR.md` (`REQ-027`)

1. **In `scripts/enforce-delegation.py` (`is_sub == True` branch)**:
   - When `tool_name in ("send_message", "default_api:send_message")`:
     - Parse transcript via `parsed = parse_transcript(payload.get("transcriptPath", ""))`.
     - Check `active_bg = parsed.get("active_bg_tasks") or []`.
     - If `active_bg`:
       - Record `SUBAGENT_TOOL_DENIED` event in `ledger`.
       - Return:
         ```json
         {
           "decision": "deny",
           "reason": "Attention Guard: Cannot call send_message while background command task(s) are still running: <ids>. Wait for each background task's <SYSTEM_MESSAGE> completion notification (by ending your turn) or explicitly terminate it via manage_task(Action=\"kill\", TaskId=\"...\") before reporting completion. Never fabricate <system_message> blocks."
         }
         ```
2. **In `rules/EXECUTOR.md`**:
   - Add constraint **`Background Task Completion Fence`**: Executor subagents must never fabricate `<system_message>` tags in responses and must never invoke `send_message` while any non-daemon background `run_command` task (`task-*`) remains `RUNNING`.

### 2.3 `send_message` Subagent Re-Dispatch Tracking & Primary Agent Watchdog Gate (`REQ-028`)

1. **Primary Agent `send_message` Hook Handling (`scripts/enforce-delegation.py`, `scripts/record-tool-result.py`, `hooks.json`)**:
   - In `scripts/enforce-delegation.py` (`not is_sub` branch), when `tool_name in ("send_message", "default_api:send_message")`:
     - Extract `recipient = str(args.get("Recipient") or args.get("recipient") or "").strip()`.
     - Extract `msg_str = str(args.get("Message") or args.get("message") or "").strip()`.
     - Verify `recipient` is non-empty and `msg_str` is valid JSON (or `os.environ.get("AGY_DISABLE_JSON_GATE") == "1"`).
     - Look up `token_id` in `tokens` where `claimed_by = recipient`. If none exists, use `work_id = recipient` and insert `(recipient, 1, now, recipient)` into `tokens`.
     - Upsert `work_items`:
       ```sql
       INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx)
       VALUES (?, 'ACTIVE', ?, ?, ?, ?, ?)
       ON CONFLICT(work_id) DO UPDATE SET
           status = 'ACTIVE',
           updated_at = excluded.updated_at,
           parent_conv_id = excluded.parent_conv_id,
           parent_turn_id = excluded.parent_turn_id,
           step_idx = excluded.step_idx
       ```
     - Record `WORK_PREPARED` (`work_id`) and `HANDOFF_ACCEPTED` (`"invoke"`) events for `(conv_id, str(turn_id), str(step_idx))` so `get_current_fsm_state(ledger, conv_id, turn_id)` transitions to `State.EXECUTION_ACTIVE`.
   - In `hooks.json`, update the `PostToolUse` matcher for `record-tool-result.py` from `"invoke_subagent"` to `"invoke_subagent|send_message"`.
2. **Dynamic `parent_turn_id` Lookup in `is_subagent()` (`scripts/common.py`)**:
   - When `is_subagent()` matches a token in `tokens` (or via `first_system_sender`), query `SELECT parent_conv_id, parent_turn_id FROM work_items WHERE work_id = ?` (or `LEFT JOIN tokens ON work_id = token_id WHERE claimed_by = ?`) and prefer the `work_items` row's `parent_conv_id` and `parent_turn_id` so re-dispatched subagents report `Stop` events to the current parent turn.
3. **Primary Agent Watchdog Verification on `Stop` (`scripts/attention-check.py`)**:
   - Parse transcript via `parsed = parse_transcript(payload.get("transcriptPath", ""))`.
   - Compute `active_bg_tasks = parsed.get("active_bg_tasks") or []` and `active_timers = parsed.get("active_timers_since_wakeup") or []`.
   - On Primary Agent `Stop` (`is_sub == False`):
     - If `len(active_bg_tasks) > 0` and `len(active_timers) == 0` (even if `current_state == State.OPEN`):
       - Reject `Stop` (`decision: "continue"`, bounded by `MAX_STOP_REJECTIONS`) requiring a 300s `schedule` watchdog timer.
     - In `current_state in (State.EXECUTION_ACTIVE, State.REVIEWING)` when `active_count > 0`:
       - If `(parsed.get("has_delegation_in_turn") or len(active_bg_tasks) > 0 or os.environ.get("AGY_FORCE_WATCHDOG_CHECK") == "1")` and `os.environ.get("AGY_REQUIRE_WATCHDOG_ON_STOP", "1") != "0"` and `len(active_timers) == 0`:
         - If `get_rejection_count(tracker) < MAX_STOP_REJECTIONS`:
           - `increment_rejection_count(tracker)`
           - Record `STOP_REQUESTED` with `{"active_work": True, "missing_watchdog": True}`
           - Return `{"decision": "continue", "reason": "Attention Guard Watchdog Gate: Active asynchronous work detected (active subagents: <active_count>, active background tasks: <len(active_bg_tasks)>) without an active 300s schedule watchdog timer since the last wakeup. You MUST arm schedule(DurationSeconds=300, TimerCondition=\"any\", Prompt=\"...\") before ending your turn, or terminate hung subagents/tasks via manage_subagents(Action=\"kill\") / manage_task(Action=\"kill\")."}`.

### 2.4 Lexical `~/.gemini/` Exclusion in `spec-gate.py` (`REQ-029`)

1. **In `/Users/thanghoang/.gemini/config/plugins/spec-driven-plugin/scripts/spec-gate.py` (`extract_prompt_workspaces`)**:
   - For each regex match `p_str` in `re.findall(r"(/[A-Za-z0-9_.\-/]+)", all_prompts)`:
     - Strip trailing punctuation: `clean_p = p_str.rstrip(".,;:)'\"")`.
     - Check if `clean_p` lexically resides under `~/.gemini/` (`"/.gemini/" in clean_p` or `clean_p.endswith("/.gemini")`):
       - If so, `continue` without resolving symlinks into plugin repositories.
