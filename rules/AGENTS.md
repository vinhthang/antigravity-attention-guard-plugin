# Attention Guard Governance & Safety Invariants

<rule name="agent-delegation">
<description>
Enforces mechanical safety guards, pragmatic multi-agent delegation, explicit plan approval, and zero error suppression without ceremony overhead.
</description>

<constraints>
- **Pragmatic Execution & Delegation**:
  - Execute quick fixes, 1–2 file edits, config updates, git operations, and `rtk`-filtered test checks directly in the Primary Agent.
  - Delegate via `invoke_subagent`, `run_workflow`, or native `swarm` when work spans 3+ disjoint files, parallel workstreams, broad read-only exploration, or noisy multi-step builds—keeping the Primary Agent's context focused on architecture and coordination.
  - **Subagent Input/Output Shape**: Delegate bounded tasks with large input context and concise summaries (never dump raw ANSI logs or full pytest traces into `send_message`).
- **Explicit Approval Gate (`/grill-me` & `/plan`)**:
  - Clarify material scope ambiguities via `ask_question` (`(Recommended)` first) before planning.
  - For multi-step features or architectural refactors, author `implementation_plan.md` in Brain Artifacts (linking rather than duplicating `docs/specs/` when present) and wait for explicit human approval ("Proceed") before executing code changes (exempt under `/goal`).
- **Mechanical Safety & Zero Error Suppression (`no-error-suppression`)**:
  - Never run sweeping destructive commands (`git reset --hard`, `git clean -f`, `git checkout .`, `git restore .`, unleased `git push --force`, catastrophic `rm -rf`) or introduce test-skipping/vacuous markers (`@pytest.mark.skip`, `pytest.skip(`, `it.skip(`, `t.Skip(`, `assert True`).
  - Fail fast: never swallow exceptions with bare `pass`, empty `catch {}`, `|| true`, or Go `_` error discards.
  - **Epistemic Honesty**: Never make speculative edits without root-cause evidence, and never silently substitute requested models, tools, or parameters. Engineer-to-engineer tone: direct, concise, factual, zero hype.
</constraints>

<instructions>
### 1. Multi-Agent Selection Guide (When Delegating)
- **Model Selection**: Use `flash_lite` (`TypeName="research"`) for broad read-only searches, `flash` for bounded code/test execution, `pro` for deep algorithmic diagnosis, or `inherit` when full parent reasoning is needed.
- **1–2 Disjoint Tasks (`invoke_subagent`)**: Spawn concurrent flat `invoke_subagent` calls in one turn with `Workspace="share"` (or `"branch"`) for disjoint file write-sets; serialize overlapping files on `Workspace="inherit"`.
- **3+ Disjoint Slices or Staged Pipelines (`run_workflow`)**: Use `run_workflow` (`phase`, `parallel`, `pipeline`, `agent(..., workspace="share")`).
- **Peer Collaboration & Verifier Loops (`swarm` / `/teamwork`)**: Use native `swarm` with `workspace="share"` for parallel authors and `workspace="inherit"` for `@verifier`, merging branches cleanly before `swarm(action="kill")`.
- **Bounded Escalation**: Cap autonomous fix attempts at 3 escalations before halting and reporting root-cause findings to the user.

### 2. Skill Routing Triggers
- When viewing or analyzing Attention Guard metrics and enforcement telemetry, consult skill `attention-metrics`.
- When managing persistent CLI git worktree sandboxes outside native `Workspace="share"` isolation, consult skill `git-worktree-sandbox`.
</instructions>
</rule>
