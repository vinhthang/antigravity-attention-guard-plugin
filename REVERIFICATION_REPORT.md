# Attention Guard Plugin Re-verification Report

## Executive Summary
A re-verification was performed to investigate whether recent code updates in `antigravity-attention-guard-plugin` addressed the 5 overly strict instructions and runtime behaviors identified in the prior audit.

**Conclusion**: **None of the 5 original findings have been resolved in the codebase.**
While the plugin underwent architectural refactoring (migrated state tracking to an SQLite database in `ledger.py`, added multi-worker lifecycle tracking, and introduced JSON schema validators), all 5 restrictive mechanisms remain active. Moreover, updates made in the active installed directory (`~/.gemini/config/plugins/attention-guard`) added even stricter constraints (Ray Dalio 5-step process, mandatory human gate, sequential-only mutating executions, and 1200-character caps).

---

## Detailed Findings

### 1. The 200-Word Cap in `EXECUTOR.md`
- **Workspace Status**: In [`rules/EXECUTOR.md`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/rules/EXECUTOR.md#L1), line 1 still reads:
  ```markdown
  You are an Execution Subagent. Execute your assigned task deterministically. Return a strict JSON payload `{"status": "completed|failed", "summary": "..."}`. Keep summaries extremely concise (max 200 words). Do NOT delegate.
  ```
  The 200-word cap is unchanged in the workspace repo.
- **Config Plugin Status**: In [`~/.gemini/config/plugins/attention-guard/rules/EXECUTOR.md`](file:///Users/thanghoang/.gemini/config/plugins/attention-guard/rules/EXECUTOR.md#L9) and [`schemas/executor-payload.json`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/schemas/executor-payload.json#L19), this was replaced with:
  `- **Summary Length**: The summary field MUST be concise, between 10 and 1200 characters.`
  `"summary": { "type": "string", "minLength": 10, "maxLength": 1200 }`
- **Impact**: 1200 characters is ~180-200 words. Rather than relaxing summary constraints for subagents, it was converted into a hard JSON schema boundary.
- **Verdict**: **NOT ADDRESSED / RIGIDIFIED**

---

### 2. Workspace Plan Writing Catch-22
- **Code Reference**: [`scripts/enforce-delegation.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/enforce-delegation.py#L64-L87)
- **Logic**:
  ```python
  if data.get("artifactDirectoryPath", "") and is_artifact_path(args.get("TargetFile", ""), data.get("artifactDirectoryPath", "")):
      if tool_name in ["write_to_file", "replace_file_content", "default_api:write_to_file", "default_api:replace_file_content"]:
          return emit({"decision": "allow"})
  ...
  emit_deny("Attention Dilution Guard: The Primary Agent is restricted to planning and artifact creation. Direct code modification and shell execution must be delegated to a subagent.")
  ```
- **Impact**: Rules require the Primary Agent to author `implementation_plan.md` and track checklists in `task.md` (`- [ ]`). However, writing to workspace files (e.g. `repo/task.md`) evaluates `is_artifact_path(...)` to `False` and is blocked by `emit_deny`. Since Phase 1 prohibits delegating to subagents before plan approval, the Primary Agent cannot write plan files in the workspace.
- **Verdict**: **NOT ADDRESSED (STILL ACTIVE)**

---

### 3. Shell Prohibitions in `enforce-delegation.py`
- **Code Reference**: [`scripts/enforce-delegation.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/enforce-delegation.py#L84-L85)
- **Logic**:
  ```python
  if tool_name in ["run_command", "default_api:run_command"]:
      return emit_deny("Attention Dilution Guard: The Primary Agent is forbidden from executing shell commands. You must delegate to a subagent.")
  ```
- **Impact**: The Primary Agent cannot execute any shell commands, including read-only status commands (`git status`, `git diff`, `git log`, read-only diagnostics).
- **Note**: A new script [`scripts/command_validator.py`](file:///Users/thanghoang/.gemini/config/plugins/attention-guard/scripts/command_validator.py) was drafted in `~/.gemini/config/plugins/attention-guard/scripts/`, defining an allowlist for `git status`, `pytest`, etc. However, it is not wired into `hooks.json` or invoked by `enforce-delegation.py`.
- **Verdict**: **NOT ADDRESSED (STILL ACTIVE)**

---

### 4. Hardcoded Coordinator Whitelists in `inject-rules.py`
- **Code Reference**: [`scripts/inject-rules.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/inject-rules.py#L40-L41)
- **Logic**:
  ```python
  else:
      child_may_delegate = type_name in ["DeepCoder", "DeepInvestigator"]
      child_depth = 1 if child_may_delegate else 0
  ```
- **Impact**: Subagents with any other `TypeName` (e.g., `Coordinator`, `Orchestrator`, `Diagnostician`, `Architect`) receive `child_may_delegate = False` and are injected with `EXECUTOR.md`. If they attempt to delegate, `enforce-delegation.py` blocks them.
- **Verdict**: **NOT ADDRESSED (STILL ACTIVE)**

---

### 5. Stop Retry Loops in `fsm.py` and `attention-check.py`
- **Code Reference**: [`scripts/attention-check.py`](file:///Users/thanghoang/github/antigravity-attention-guard-plugin/scripts/attention-check.py#L118-L126)
- **Logic**:
  ```python
  if current_state == State.RECOVERY_REQUIRED:
      rejection_count = get_rejection_count(tracker)
      if rejection_count >= MAX_STOP_REJECTIONS:
          reset_rejection_count(tracker)
          ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"retries_exhausted": True}))
          return emit({"decision": "allow"})
      rejection_count = increment_rejection_count(tracker)
      return emit({"decision": "continue", "reason": f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"})
  ```
- **Impact**: Any tool denial transitions FSM state to `RECOVERY_REQUIRED`. When the agent attempts to complete its turn (e.g. to reply to the user or ask for clarification), `attention-check.py` rejects the stop with `decision: "continue"`, forcing repeated loops until `MAX_STOP_REJECTIONS` is hit.
- **Verdict**: **NOT ADDRESSED (STILL ACTIVE)**

---

## Newly Introduced Discrepancies and Rules

1. **State Divergence between Workspace and Config Plugin**:
   - `github/antigravity-attention-guard-plugin` is missing `command_validator.py`, `deploy_plugin.py`, and has older `rules/`.
   - `github/antigravity-attention-guard-plugin/scripts/payload_validator.py` crashes on import (`ModuleNotFoundError: No module named 'jsonschema'`) because `jsonschema` is not installed. The config plugin directory contains an updated version with a fallback (`validate_payload_builtin`), which was not synced to the workspace.
2. **New Restrictive Constraints in `rules/AGENTS.md`**:
   - Phase 1 Human Gate: All code mutations and subagent runs are gated behind explicit user prompt ("Proceed").
   - Mutating Concurrency Invariant: Mutating tasks must execute strictly sequentially.
   - Strict UUID (`execution_attempt_id`) and Schema Enforcement.
   - Mandatory 300s liveness timers for all subagent invocations.

---

## Remaining Questions & Gaps
1. **Source of Truth**: Need clarification on whether `~/.gemini/config/plugins/attention-guard` or `/Users/thanghoang/github/antigravity-attention-guard-plugin` is the designated primary development workspace.
2. **Hook Integration**: Determine if `command_validator.py` and `payload_validator.py` were meant to be integrated into `hooks.json` or replaced with lightweight checks.
3. **Recommended Fixes**:
   - Update `enforce-delegation.py` to allow Primary Agent read-only shell commands and workspace plan authoring.
   - Replace hardcoded `TypeName` whitelists with configurable role metadata.
   - Soften `RECOVERY_REQUIRED` in `attention-check.py` to allow normal user responses without Stop rejection loops.
