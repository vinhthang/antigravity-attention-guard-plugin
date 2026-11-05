# Verification Evidence: Subagent Background Task Completion Fence, `send_message` Re-Dispatch Tracking, Watchdog Enforcement & Telemetry Alignment

**Feature ID**: `2026-10-31-subagent-task-fence-and-watchdog-enforcement`  
**Execution Date**: `2026-11-05`  
**Status**: `Verified`  
**Governing Requirements**: `REQ-027`, `REQ-028`, `REQ-029`, `REQ-031`, `REQ-032`

---

## 1. Targeted TDD Regression Tests

Verbatim execution of unit and regression tests covering all 5 feature requirements:

```
$ pytest -v tests/test_ledger_performance.py tests/test_attention_refresh.py tests/test_surface_validator.py -k "req_027 or req_028 or req_029 or req_031 or req_032"
============================= test session starts ==============================
platform darwin -- Python 3.11.6, pytest-9.1.1, pluggy-1.6.0 -- /Users/thanghoang/.local/share/uv/tools/pytest/bin/python
cachedir: .pytest_cache
rootdir: /Users/thanghoang/github/antigravity-attention-guard-plugin
plugins: asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 51 items / 45 deselected / 6 selected                                

tests/test_ledger_performance.py::test_req_027_subagent_task_fence_on_send_message PASSED [ 16%]
tests/test_ledger_performance.py::test_req_028_send_message_redispatch_and_watchdog_gate PASSED [ 33%]
tests/test_ledger_performance.py::test_req_029_extract_prompt_workspaces_gemini_symlink_exclusion PASSED [ 50%]
tests/test_ledger_performance.py::test_req_031_ledger_turns_lifecycle_and_prune PASSED [ 66%]
tests/test_attention_refresh.py::test_req_031_active_context_chars_and_refresh_calculation PASSED [ 83%]
tests/test_surface_validator.py::test_req_032_autotrigger_custom_rule_file_fallback PASSED [100%]

======================= 6 passed, 45 deselected in 0.18s =======================
```

### Requirement-to-Test Mapping
- `REQ-027`: `tests/test_ledger_performance.py::test_req_027_subagent_task_fence_on_send_message`
  - Validates `enforce-delegation.py` blocks subagent `send_message` when background tasks (`active_bg_tasks`) remain uncompleted.
  - Validates synthetic `<system_message>` in `MODEL` `PLANNER_RESPONSE` steps does not clear `active_bg_tasks`.
  - Validates genuine `SYSTEM` `SYSTEM_MESSAGE` task finish notification clears `active_bg_tasks` and allows `send_message`.
- `REQ-028`: `tests/test_ledger_performance.py::test_req_028_send_message_redispatch_and_watchdog_gate`
  - Validates Primary Agent `send_message` re-dispatch reactivates `work_items` to `ACTIVE` with `(parent_conv_id, parent_turn_id, step_idx)`.
  - Validates `WORK_PREPARED` and `HANDOFF_ACCEPTED` event emissions.
  - Validates Primary Agent `Stop` gate requires 300s `schedule` watchdog timer when active work exists.
  - Validates Primary Agent `Stop` succeeds once 300s `schedule` watchdog timer is armed.
- `REQ-029`: `tests/test_ledger_performance.py::test_req_029_extract_prompt_workspaces_gemini_symlink_exclusion`
  - Validates `extract_prompt_workspaces` ignores `/.gemini/` lexical paths and strips trailing punctuation, preventing symlink resolution into plugin repos from external projects.
- `REQ-031`: `tests/test_ledger_performance.py::test_req_031_ledger_turns_lifecycle_and_prune` & `tests/test_attention_refresh.py::test_req_031_active_context_chars_and_refresh_calculation`
  - Validates `Ledger.sync_session_chars` incremental and cumulative token statistics updates.
  - Validates `turns` table insertion on `WORK_PREPARED`, `STOP_REQUESTED`, and `TURN_CLOSED`.
  - Validates `Ledger.prune` deletes `CLOSED` turns older than retention window.
  - Validates `parse_transcript` calculates `active_context_chars` across valid JSON steps while excluding `thinking` traces and resetting across compaction boundaries.
  - Validates `attention-refresh.py` token volume trigger grounding on `active_context_chars`.
- `REQ-032`: `tests/test_surface_validator.py::test_req_032_autotrigger_custom_rule_file_fallback`
  - Validates `_resolve_autotrigger_target` falls back to the first sorted `rules/*.md` file when `rules/AGENTS.md` is absent.
  - Validates `validate_plugin_surface(..., repair_triggers=True)` writes skill triggers to custom rule files.

---

## 2. Complete Plugin Test Suite (`antigravity-attention-guard-plugin`)

```
$ pytest tests/
============================= test session starts ==============================
platform darwin -- Python 3.11.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/thanghoang/github/antigravity-attention-guard-plugin
plugins: asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 198 items                                                            

tests/test_advanced_fsm.py ...                                           [  1%]
tests/test_attention_check.py .......                                    [  5%]
tests/test_attention_refresh.py ..................                       [ 14%]
tests/test_community_must_todos.py ....................                  [ 24%]
tests/test_dalio_conformance.py ..............                           [ 31%]
tests/test_deploy_plugin.py ..                                           [ 32%]
tests/test_e2e_hook_pipeline.py ....                                     [ 34%]
tests/test_enforce_delegation.py ....................................... [ 54%]
......                                                                   [ 57%]
tests/test_harness2_improvements.py ...........................          [ 70%]
tests/test_inject_rules.py .............                                 [ 77%]
tests/test_large_prompt.py .                                             [ 77%]
tests/test_ledger_performance.py .................                       [ 86%]
tests/test_surface_validator.py ................                         [ 94%]
tests/test_sync_metrics.py .....                                         [ 96%]
tests/test_system_message_subagent.py ......                             [100%]

======================== 198 passed, 1 warning in 2.60s ========================
```

---

## 3. External Plugin Test Suite (`spec-driven-plugin`)

```
$ pytest /Users/thanghoang/github/spec-driven-plugin/tests
============================= test session starts ==============================
platform darwin -- Python 3.11.6, pytest-9.1.1, pluggy-1.6.0
rootdir: /Users/thanghoang/github
plugins: asyncio-1.4.0, anyio-4.15.1
asyncio: mode=Mode.STRICT, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collecting ... collected 60 items                                                             

../spec-driven-plugin/tests/test_spec_checker.py ....................... [ 38%]
..                                                                       [ 41%]
../spec-driven-plugin/tests/test_spec_gate.py ...................        [ 73%]
../spec-driven-plugin/tests/test_spec_gate_security.py ................  [100%]

============================== 60 passed in 0.37s ==============================
```

---

## 4. Antigravity Ecosystem Audit (`system_audit.py`)

Verbatim audit confirmation of zero ecosystem errors across all installed plugins and SQLite ledger health (`REQ-032` remediation):

```
$ python3 scripts/system_audit.py
=== Antigravity Ecosystem Audit ===
Overall Valid: True
Total Errors : 0

--- Plugins (6) ---
  [PASS] agent-translator (/Users/thanghoang/github/agent-translator)
  [PASS] ai-review-plugin (/Users/thanghoang/github/ai-review-plugin)
  [PASS] attention-guard (/Users/thanghoang/github/antigravity-attention-guard-plugin)
  [PASS] gitleaks-guard (/Users/thanghoang/.gemini/config/plugins/gitleaks-guard)
  [PASS] google-cloud-developer (/Users/thanghoang/.gemini/config/plugins/google-cloud-developer)
  [PASS] spec-driven-plugin (/Users/thanghoang/github/spec-driven-plugin)

--- SQLite Ledger (/Users/thanghoang/.gemini/antigravity/attention_guard.db) ---
  Total Work Items: 198
  Counts Breakdown: {'ACTIVE': 2, 'COMPLETED': 147, 'TERMINATED': 48, 'TIMED_OUT': 1}
```

---

## 5. Mutation Guard Falsifiability Audit

Verbatim mutation testing execution verifying test suite assertion rigor and falsifiability on modified components:

### 5.1 `scripts/attention-refresh.py` (100.0% Kill Rate)

```
$ rtk python3 ~/.gemini/config/skills/mutation-guard/scripts/mutation_runner.py --target-file scripts/attention-refresh.py --test-cmd "pytest -q tests/test_attention_refresh.py"

[Mutation Guard] Analyzing Python target: scripts/attention-refresh.py
Found 22 candidate mutation sites. Testing up to 20 mutants...
  Line   29 | >= to >          | 🎯 KILLED
  Line   31 | >= to >          | 🎯 KILLED
  Line   33 | >= to >          | 🎯 KILLED
  Line   35 | >= to >          | 🎯 KILLED
  Line   38 | is to is not     | 🎯 KILLED
  Line   41 | is to is not     | 🎯 KILLED
  Line   44 | > to >=          | 🎯 KILLED
  Line   59 | != to ==         | 🎯 KILLED
  Line   65 | >= to >          | 🎯 KILLED
  Line   94 | is to is not     | 🎯 KILLED
  Line   96 | == to !=         | 🎯 KILLED
  Line  109 | is to is not     | 🎯 KILLED
  Line  110 | is to is not     | 🎯 KILLED
  Line  112 | == to !=         | 🎯 KILLED
  Line  133 | <= to <          | 🎯 KILLED
  Line  162 | == to !=         | 🎯 KILLED
  Line  167 | < to <=          | 🎯 KILLED
  Line  173 | >= to >          | 🎯 KILLED
  Line  181 | > to >=          | 🎯 KILLED
  Line  181 | == to !=         | 🎯 KILLED

==================================================
Mutation Score: 100.0% (20/20 killed)
🎉 All mutants killed! Test suite is strictly falsifiable.
==================================================
```

### 5.2 `scripts/surface_validator.py` (93.8% Kill Rate)

```
$ rtk python3 ~/.gemini/config/skills/mutation-guard/scripts/mutation_runner.py --target-file scripts/surface_validator.py --test-cmd "pytest -q tests/test_surface_validator.py"

[Mutation Guard] Analyzing Python target: scripts/surface_validator.py
Found 16 candidate mutation sites. Testing up to 16 mutants...
  Line  110 | == to !=         | 🎯 KILLED
  Line  110 | == to !=         | 🎯 KILLED
  Line  123 | < to <=          | 🎯 KILLED
  Line  184 | is not to is     | 🎯 KILLED
  Line  215 | <= to <          | 🎯 KILLED
  Line  234 | != to ==         | 🎯 KILLED
  Line  307 | == to !=         | 🎯 KILLED
  Line  316 | == to !=         | 🎯 KILLED
  Line  338 | is not to is     | 🎯 KILLED
  Line  355 | > to >=          | 🎯 KILLED
  Line  373 | != to ==         | 🎯 KILLED
  Line  401 | >= to >          | ⚠️  SURVIVED
  Line  437 | == to !=         | 🎯 KILLED
  Line  441 | == to !=         | 🎯 KILLED
  Line  457 | != to ==         | 🎯 KILLED
  Line  494 | == to !=         | 🎯 KILLED

==================================================
Mutation Score: 93.8% (15/16 killed)

⚠️  Surviving Mutants (Test Assertions Needed):
  - Line 401: Inverting '>= to >' did not break any test! Harden boundary assertions.
==================================================
```

---

## 6. Independent Code Review Verification

Independent peer review executed via `ai-review-plugin` (`deepseek-v4.1-flash`, WorkBuddy engine):

```
$ rtk python3 ~/.gemini/config/plugins/ai-review-plugin/scripts/peer_review.py \
    --target /Users/thanghoang/github/antigravity-attention-guard-plugin/.code-review/diff.patch \
    --mode code \
    --repo /Users/thanghoang/github/antigravity-attention-guard-plugin \
    --output-file /Users/thanghoang/github/antigravity-attention-guard-plugin/review.json
```

### Review Verdict: **PASS**
- **P0 Issues**: 0
- **P1 Issues (Remediated & Verified)**:
  1. `scripts/common.py`: Positional pop in background-task association replaced with bidirectional `toolSummary`/`CommandLine` matching against task description; synchronous exits pop matching commands.
  2. `scripts/common.py`: Watchdog duration validation enforced end-to-end; GENERIC `Task Description: Timer:` steps only admit task IDs correlating to verified $\ge 60\text{s}$ non-cron schedule calls.
  3. `scripts/attention-check.py`: Evaluated `ledger.reconcile_orphaned_work_items()` before active work counting so orphaned items transition to `TERMINATED` without falsely blocking the Stop gate.
- **P2 Issues (Remediated & Documented)**:
  1. `scripts/attention-check.py`: Watchdog rejection event recorded under distinct `execution_idx` (`f"reject_{rejection_count}"`), preventing deduplication of final turn closure `STOP_REQUESTED`.
  2. `scripts/record-tool-result.py`: Handoff event emission retrieves and aligns with the work item's `step_idx`.
  3. `scripts/ledger.py`: `sync_session_chars` uses `new_total = max(prev_total, total_chars)` for monotonic session stats tracking.
  4. Traceability package hash verified against `compute_spec_package_hash` in `spec_checker.py`.
- Complete documentation saved to `review.md`.
