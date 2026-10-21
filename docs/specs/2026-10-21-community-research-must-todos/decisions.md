# Architectural Decision Records: Community & Literature Must-To-Do Hardening

## ADR-001: Dual-Schema Support for Antigravity 1.x and 2.0 Tool Payloads (`REQ-007`)
- **Status**: Accepted
- **Context**: Antigravity 2.0 declares `write_file` and `edit_file` (with `Path`) and flat `invoke_subagent` parameters (`TypeName`, `Role`, `Prompt`), whereas existing hooks only checked `write_to_file`, `replace_file_content`, `TargetFile`, and `Subagents=[...]`.
- **Decision**: Normalize file-mutation tool names, target path keys (`Path`, `TargetFile`, `target_file`, `path`, `file_path`), and `invoke_subagent` arguments across `enforce-delegation.py` and `inject-rules.py`.

## ADR-002: Mechanical PreToolUse Guards for Test Tampering, Doom Loops & Destructive Commands (`REQ-008`, `REQ-009`, `REQ-010`)
- **Status**: Accepted
- **Context**: Community research (`agent-guard`, `claude-guard-hooks`, `dwarvesf/claude-guardrails`) demonstrates that prose rules in `EXECUTOR.md` or `tdd.md` decay under retry pressure. Subagents may skip tests, repeat identical failing commands, or run `git reset --hard`.
- **Decision**: Enforce all three guards deterministically inside `enforce-delegation.py` (`check_test_tampering`, `check_subagent_doom_loop`, `check_destructive_command`).

## ADR-003: Live Context Telemetry, Pre-Compaction Checkpointing & Observation Masking (`REQ-011`, `REQ-012`, `REQ-013`)
- **Status**: Accepted
- **Context**: Based on Anthropic Context Engineering, NeurIPS *"The Complexity Trap"* (arXiv:2508.21433), and GitHub `mengram`, agents need explicit context-window fullness telemetry, pre-compaction state checkpoints on disk, rejection of raw terminal dumps in subagent summaries, and turn-scoped freshness checks on `walkthrough.md`.
- **Decision**: Upgrade `attention-refresh.py`, `payload_validator.py`, and `attention-check.py` with zero external dependencies.

## ADR-004: Antigravity 2.0 `Stop` `terminationReason` Alignment & End-to-End Subprocess Hook Auditing (`REQ-014`, `REQ-015`)
- **Status**: Accepted
- **Context**: Live SQLite database inspection (`~/.gemini/antigravity/attention_guard.db`) revealed `0` `COMPLETED` rows and `727` `TIMED_OUT` rows out of `741` `work_items` because `attention-check.py` checked `terminationReason == "model_stop"` instead of Antigravity 2.0's `"NO_TOOL_CALL"` (`docs/hooks.md`), which also prevented `active_count` from reaching `0` and silently bypassed the Walkthrough Gate in production. Isolated unit tests missed this because they mocked `"model_stop"`.
- **Decision**: Support all Antigravity 2.0 `ExecutorTerminationReason` values in `attention-check.py`, add `step_index: 0` `sender=<uuid>` subagent detection in `common.py`, build `tests/test_e2e_hook_pipeline.py` to test the full multi-plugin hook pipeline end-to-end via real `hooks.json` matchers, and provide `scripts/system_audit.py` for continuous cross-plugin and SQLite ledger auditing.
