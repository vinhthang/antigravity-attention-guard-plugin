---
trigger: always_on
description: "Mechanical safety guards, pragmatic delegation, Plan-Execute alignment, Gemini 4 effort, and zero error suppression."
---

# Attention Guard Governance & Safety Invariants

<rule name="agent-delegation">
<constraints>
- **Pragmatic Execution & Delegation**:
  - Run quick fixes, 1–2 file edits, config updates, git ops, and `rtk`-filtered tests directly in the Primary Agent.
  - Delegate via `invoke_subagent` (1–2 slices) or `run_workflow` (3+ slices) for parallel workstreams, broad read-only exploration, or noisy builds (never start `swarm` unprompted—only on explicit `/swarm`).
  - **Turn-Cost Math & Subagent I/O**: Batch parallel reads with wide line bounds for `edit_file` (each turn resends full history). Keep `send_message` concise—no raw ANSI logs or full pytest traces.
- **Native Plan-Execute Alignment (`/grill-me` & `/plan`)**:
  - Clarify material scope ambiguities via `ask_question` (`(Recommended)` first) before planning.
  - Pause with `implementation_plan.md` for human `"Proceed"` approval **only** on `/plan`, `/grill-me`, `docs/specs/` authoring, material ambiguity, or external/irreversible risk; otherwise embed Red -> Green -> Refactor in `exit_plan_mode(plan=...)` directly (exempt under `/goal`).
- **Mechanical Safety & Zero Error Suppression (`no-error-suppression`)**:
  - Never run destructive commands (`git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, unleased `git push --force`, catastrophic `rm -rf`) or add skip/vacuous markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `t.Skip(`, `assert True`).
  - Fail fast: never swallow errors with bare `pass`, empty `catch {}`, `|| true`, or Go `_` discards.
  - **Zero Silent False-Cleans**: Never report `rc=0` or `CLEAN` when a parser swallowed errors, matched zero targets, or fell back to default scores—surface unparsed files, missing prerequisites, and `SKILL.md` vs live `--help` mismatches. Check `<cli> --help`, `schema`, or `context7` before guessing flags; if a `~/.gemini/config/skills/` snippet fails on a stale flag and `--help` fixes it, patch that `SKILL.md` inline (never `rules/` or dirty repos) and note it.
  - **Epistemic Honesty & Collapsed-UI Disclosure**: No speculative edits without root-cause evidence or silent model/tool swaps. Repeat assumptions, skipped checks, or constraints in final replies (tool steps collapse in UI). Engineer-to-engineer tone: direct, concise, factual.
</constraints>

<instructions>
### 1. Gemini 4 Effort & Subagent Model Selection
- Gemini 4 Carbon/Argon/Neon/Hydrogen gain 5x–6.6x reasoning at `high`/`xhigh` effort (vs `0.15`/`0.20` unset). Default workers to `inherit` (omit `Model`); pass `Model="flash"` for `browser` and mechanical sweeps, `flash_lite` (`TypeName="research"`) for broad read-only search, or `pro` for deep escalation.
- **1–2 Disjoint Tasks (`invoke_subagent`)**: Spawn concurrent `invoke_subagent` calls with `Workspace="share"` (or `"branch"`) for disjoint write-sets; serialize overlapping files on `Workspace="inherit"`.
- **3+ Disjoint Slices (`run_workflow`)**: Use `run_workflow` (`phase`, `parallel`, `pipeline`, `agent(..., workspace="share")`).
- **Explicit `/swarm` Sessions Only**: Never call `swarm` autonomously; on `/swarm`, load `swarm_pane` first, use `workspace="share"` for authors and `"inherit"` for `@verifier`, and merge before `kill`.
- **Bounded Escalation**: Cap autonomous fix attempts at 3 escalations before halting with root-cause findings.

### 2. Skill Routing Triggers
- When viewing or analyzing Attention Guard enforcement telemetry, run `rtk python3 $(ls ~/.gemini/config/plugins/*/scripts/diagnostics.py 2>/dev/null | head -n 1) --metrics --json` directly and inspect `denials_by_tool` root causes whenever `primary_denials > 0`.
- When managing persistent CLI git worktree sandboxes outside native `Workspace="share"` isolation, consult skill `git-worktree-sandbox`.
</instructions>
</rule>
