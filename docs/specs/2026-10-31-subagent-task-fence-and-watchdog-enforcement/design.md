# Technical Design: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking, Watchdog Enforcement & Telemetry Alignment

## 1. Architectural Mapping to Requirements

| Component | File(s) | Requirement IDs |
|---|---|---|
| Transcript Task, Timer & Active Context Parser (`active_bg_tasks`, `active_timers_since_wakeup`, `active_context_chars`) | `scripts/common.py` | `Addresses: REQ-027, REQ-028, REQ-031` |
| Subagent `send_message` Background Task Fence & Executor Rules | `scripts/enforce-delegation.py`, `rules/EXECUTOR.md` | `Addresses: REQ-027` |
| Primary Agent `send_message` Re-Dispatch Ledger Activation & `is_subagent()` Turn Resolution | `scripts/enforce-delegation.py`, `scripts/record-tool-result.py`, `scripts/common.py`, `hooks.json` | `Addresses: REQ-028` |
| Primary Agent `Stop` Watchdog Timer Verification | `scripts/attention-check.py` | `Addresses: REQ-028` |
| Lexical `~/.gemini/` Symlink Exclusion in Prompt Workspace Extraction | `/Users/thanghoang/.gemini/config/plugins/spec-driven-plugin/scripts/spec-gate.py` | `Addresses: REQ-029` |
| Content-Grounded Refresh Telemetry, `session_stats` Sync & `turns` Table Lifecycle | `scripts/attention-refresh.py`, `scripts/ledger.py`, `scripts/common.py` | `Addresses: REQ-031` |
| Custom Rule File Autotrigger Fallback & `google-cloud-developer` Surface Remediation | `scripts/surface_validator.py`, `/Users/thanghoang/.gemini/config/plugins/google-cloud-developer/rules/google-cloud-discovery.md` | `Addresses: REQ-032` |

---

## 2. Detailed Component Design

### 2.1 Transcript Task, Timer & Active Context Tracking in `parse_transcript()` (`REQ-027`, `REQ-028`, `REQ-031`)

1. **Extend `parse_transcript(transcript_path: str) -> dict` in `scripts/common.py`**:
   - Add keys to the returned dictionary:
     - `"active_bg_tasks": list[str]` — ordered list of uncompleted, non-daemon background `run_command` task IDs (`<conv_id>/task-<N>`).
     - `"active_timers_since_wakeup": list[str]` — ordered list of active `schedule` timer task IDs (`<conv_id>/task-<N>` or synthetic `schedule_call_<idx>`) spawned since the last `USER_INPUT` or `SYSTEM` `SYSTEM_MESSAGE` step.
     - `"has_delegation_in_turn": bool` — `True` if any `PLANNER_RESPONSE` step in the current turn invoked `invoke_subagent`, `default_api:invoke_subagent`, `send_message`, or `default_api:send_message`.
     - `"active_context_chars": int` — cumulative character count of `content` and `tool_calls` across valid JSON steps since the start of the transcript or the latest compaction boundary (`type == "COMPACTION"` or `"compacted"` in `type.lower()`), excluding `thinking` fields and JSONL wrapper keys.
     - `"has_valid_json_steps": bool` — `True` if at least one line in `transcript_path` parsed as a non-empty JSON dict.
   - **Step-by-step state transitions while iterating `steps`**:
     - Track `last_planner_had_daemon_cmd = False`, `current_turn_delegated = False`, `active_context_chars = 0`, and `has_valid_json_steps = False`.
     - For each parsed `step` (when `isinstance(step, dict)` and `bool(step)`):
       - Set `has_valid_json_steps = True`.
       - If `stype == "COMPACTION"` or `"compacted"` in `str(stype).lower()`:
         - Reset `active_context_chars = 0`.
       - Add `len(str(step.get("content") or ""))` to `active_context_chars`.
       - If `step.get("tool_calls")`:
         - Add `len(json.dumps(step.get("tool_calls")))` to `active_context_chars`.
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
     - Parse transcript via `parsed = parse_transcript(data.get("transcriptPath", ""))`.
     - Check `active_bg = parsed.get("active_bg_tasks") or []`.
     - If `active_bg`:
       - Return `emit_deny(...)`:
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
     - Verify `recipient` is non-empty and (`msg_str` starts with `{` or `os.environ.get("AGY_DISABLE_JSON_GATE") == "1"`).
     - Look up `token_id` in `tokens` where `claimed_by = recipient`. If none exists, use `work_id = recipient` and insert `(recipient, 1, recipient, now)` into `tokens`.
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
     - Record `WORK_PREPARED` (`work_id`) event for `(conv_id, str(turn_id), "PreToolUse", str(step_idx))` so `get_current_fsm_state(ledger, conv_id, turn_id)` transitions to `State.HANDOFF_PENDING` (and `State.EXECUTION_ACTIVE` upon `PostToolUse` in `record-tool-result.py`).
   - In `hooks.json`, update the `PostToolUse` matcher for `record-tool-result.py` from `"invoke_subagent"` to `"invoke_subagent|send_message"`.
2. **Dynamic `parent_turn_id` Lookup & One-Shot `WORK_CLAIMED` in `is_subagent()` (`scripts/common.py`)**:
   - Check whether the token was already claimed prior to `ledger.claim_token(token, conv_id)` so `WORK_CLAIMED` and `RUNNING` events are only inserted when the token is first claimed.
   - Query `SELECT parent_conv_id, parent_turn_id FROM work_items WHERE work_id = ?` and override `parent_conv_id` and `parent_turn_id` from `work_items` when non-empty so re-dispatched subagents report `WAITING` and `WORK_TERMINATED_OK` to the latest parent turn.
   - When `first_system_sender` fallback is used (`tokens` empty), also check `SELECT parent_conv_id, parent_turn_id FROM work_items w LEFT JOIN tokens t ON w.work_id = t.token_id WHERE t.claimed_by = ? OR w.work_id = ?` to resolve the active `parent_turn_id`.
3. **Primary Agent Watchdog Verification on `Stop` (`scripts/attention-check.py`)**:
   - Parse transcript via `parsed = parse_transcript(payload.get("transcriptPath", ""))`.
   - Compute `active_bg_tasks = parsed.get("active_bg_tasks") or []` and `active_timers = parsed.get("active_timers_since_wakeup") or []`.
   - On Primary Agent `Stop` (`is_sub == False`):
     - If `len(active_bg_tasks) > 0` and `len(active_timers) == 0` and `os.environ.get("AGY_REQUIRE_WATCHDOG_ON_STOP", "1") != "0"`:
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

### 2.5 Active Context Token Telemetry, `session_stats` Sync & `turns` Table Lifecycle (`REQ-031`)

1. **In `scripts/ledger.py`**:
   - Add `Ledger.sync_session_chars(self, session_id: str, total_chars: int)`:
     ```python
     def sync_session_chars(self, session_id: str, total_chars: int):
         now = time.time()
         with self._get_connection() as conn:
             row = conn.execute(
                 "SELECT total_session_chars, chars_since_refresh FROM session_stats WHERE session_id = ?",
                 (session_id,),
             ).fetchone()
             if row is None:
                 conn.execute(
                     "INSERT INTO session_stats (session_id, total_session_chars, chars_since_refresh, updated_at) VALUES (?, ?, ?, ?)",
                     (session_id, total_chars, total_chars, now),
                 )
             else:
                 prev_total = row[0] or 0
                 prev_since = row[1] or 0
                 delta = max(0, total_chars - prev_total)
                 conn.execute(
                     "UPDATE session_stats SET total_session_chars = ?, chars_since_refresh = ?, updated_at = ? WHERE session_id = ?",
                     (total_chars, prev_since + delta, now, session_id),
                 )
     ```
   - In `Ledger.insert_event()`:
     - When `event_type in ("WORK_PREPARED", "STOP_REQUESTED", "TURN_CLOSED")` and `actor_id != "unknown"`:
       - Map `turn_status = "CLOSED" if event_type == "TURN_CLOSED" else ("EXECUTION_ACTIVE" if event_type == "WORK_PREPARED" else "STOP_REQUESTED")`.
       - Execute:
         ```sql
         INSERT INTO turns (turn_id, status, created_at)
         VALUES (?, ?, ?)
         ON CONFLICT(turn_id) DO UPDATE SET status = excluded.status
         ```
         with `turn_key = f"{actor_id}_{turn_id}"`.
   - In `Ledger.prune()`:
     - Execute `DELETE FROM turns WHERE status = 'CLOSED' AND created_at < ?` with `(now - retention_seconds,)` and include `"turns_deleted": cur_turns.rowcount` in the returned dictionary.
2. **In `scripts/attention-refresh.py`**:
   - When `transcript_path and os.path.exists(transcript_path)`:
     - Call `parsed = parse_transcript(transcript_path)`.
     - If `parsed.get("has_valid_json_steps")`:
       - Set `active_chars = parsed.get("active_context_chars", 0)`.
       - Set `total_tokens = active_chars // 4`.
       - Call `ledger.sync_session_chars(session_id, active_chars)`.
     - Else:
       - Fall back to `total_tokens = os.path.getsize(transcript_path) // 4`.

### 2.6 Custom Rule File Autotrigger Fallback & `google-cloud-developer` Surface Audit Remediation (`REQ-032`)

1. **In `scripts/surface_validator.py`**:
   - Add helper `_resolve_autotrigger_target(surface: PluginSurfaceSpec, tree: dict[str, str]) -> str`:
     - If `surface.autotrigger_file in tree`, return `surface.autotrigger_file`.
     - Otherwise, find `rule_files = sorted(p for p in tree if p.startswith("rules/") and p.endswith(".md"))`.
     - Return `rule_files[0]` if `rule_files` is non-empty, else `surface.autotrigger_file`.
   - Use `_resolve_autotrigger_target(surface, tree)` in `autotrigger()` and `validate_plugin_surface(..., repair_triggers=True)` so plugins with a custom rule file (`rules/google-cloud-discovery.md`) have missing triggers appended directly to that file.
2. **In `/Users/thanghoang/.gemini/config/plugins/google-cloud-developer/rules/google-cloud-discovery.md`**:
   - Run `surface_validator.py --autotrigger` on `/Users/thanghoang/.gemini/config/plugins/google-cloud-developer` (appending the 4 bundled skill trigger lines for `gcloud`, `google-cloud-recipe-auth`, `google-cloud-recipe-onboarding`, and `retrieving-developer-knowledge` while keeping `always_on_chars <= 8000`) and verify `rtk python3 scripts/system_audit.py` exits with `0`.
