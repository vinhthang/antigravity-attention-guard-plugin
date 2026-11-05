# Architectural Decisions (ADR): Standalone Marketplace Packaging

**Feature ID**: `2026-11-05-standalone-marketplace-packaging`  
**Status**: `draft`

---

## `ADR-001` — Bundling `json-gate` into `attention-guard` & Retiring Deprecated `ast-gate` (`REQ-033`, `REQ-037`)

### Context
Previously, `json-gate.py` (`PreToolUse` on `send_message`) and `ast-gate.py` (`PreToolUse` on `read_file|view_file` blocking >500-line reads) were configured in `~/.gemini/config/hooks.json` pointing to `~/.gemini/config/scripts/`. The 500-line `ast-gate` rule was intended to be retired, whereas `json-gate` is required by `attention-guard` to enforce structured JSON handoffs on `send_message`.

### Decision
1. Merge `json-gate` validation directly into `scripts/enforce-delegation.py` on `send_message` (and ship `scripts/json-gate.py` in `scripts/` for direct invocation or unit testing): validate that `Message` parses to a JSON `dict` (unless `AGY_DISABLE_JSON_GATE == "1"`) and run any `verify_cmd` with a 15-second timeout before permitting the handoff.
2. Permanently remove `ast-gate` from `~/.gemini/config/hooks.json` and delete `~/.gemini/config/scripts/ast-gate.py`, without adding any 500-line file-read blocker to `attention-guard`.

### Trade-offs & Risks
- **Trade-off**: Merging `json-gate` into `enforce-delegation.py` requires existing unit tests that pass plain-string `Message` payloads without `AGY_DISABLE_JSON_GATE` to either send JSON dicts or set `AGY_DISABLE_JSON_GATE=1`.
- **Mitigation**: All structured handoffs in `attention-guard` already use JSON dicts (`{"status": "completed", ...}` or `{"task": "..."}`), and `AGY_DISABLE_JSON_GATE=1` remains supported as an explicit escape hatch.

### Rejected Alternatives
- **Bundle `ast-gate.py` into `attention-guard`**: Rejected per user confirmation that the 500-line file read block should be removed rather than carried forward.

---

## `ADR-002` — Modular Single-Purpose Boundary & `templates/` Separation (`REQ-034`)

### Context
The Antigravity Language Server (`GetAllPlugins`) loads every `.md` file inside a plugin's `rules/` directory into the active rule set. Having `rules/EXECUTOR.md` and `rules/COORDINATOR.md` inside `rules/` caused subagent-only instructions to register as Primary Agent rules. Furthermore, `attention-guard` must work standalone for any Marketplace user without requiring `spec-driven-plugin` (`docs/specs/`) or `ai-review-plugin` (`code-review`).

### Decision
1. Move `rules/EXECUTOR.md` and `rules/COORDINATOR.md` to `templates/EXECUTOR.md` and `templates/COORDINATOR.md` (with `scripts/inject-rules.py` checking `templates/` first and falling back to `rules/`).
2. Consolidate only the rules intrinsic to Attention Guard (`agent-delegation`, standalone Phase 0/1/2 plan approval gating, `no-error-suppression`, and `reasoning-quality` root-cause discipline) into a single high-density `rules/AGENTS.md` file strictly bounded by `always_on_max <= 8000` characters, with zero hard dependency on `spec-driven-plugin` or `ai-review-plugin`.

### Trade-offs & Risks
- **Trade-off**: Keeping `spec-driven-plugin`, `ai-review-plugin`, and general TDD/AST skills separate means users who want 5-Document specs or multi-model peer reviews install those companion plugins separately.
- **Mitigation**: This preserves strict single-responsibility modularity ("One coherent purpose per plugin") so `attention-guard` works out of the box with zero external dependencies.

### Rejected Alternatives
- **Monolithic all-in-one plugin**: Rejected because bundling unrelated skills (`ast-grep`, `mutation-guard`, `spec-driven`, `ai-review`) into `attention-guard` violates plugin modularity and forces users into an all-or-nothing toggle.

---

## `ADR-003` — Bundling `git-worktree-sandbox` & Portable Plugin Path Resolution (`REQ-035`, `REQ-036`, `REQ-037`)

### Context
Marketplace plugins are installed into `~/.gemini/config/plugins/<signed-int64-hash>/` rather than `~/.gemini/config/plugins/attention-guard/`. Hardcoded paths like `/Users/thanghoang/.gemini/config/plugins/attention-guard/...` or workspace-relative `scripts/diagnostics.py` fail for Marketplace installs and non-`thanghoang` users.

### Decision
1. Bundle `git-worktree-sandbox` (subagent git worktree isolation) alongside `attention-metrics` inside `skills/` in `antigravity-attention-guard-plugin`.
2. Strip all `/Users/thanghoang` references, and use portable wildcard discovery (`$(ls ~/.gemini/config/plugins/*/scripts/payload_validator.py 2>/dev/null | head -n 1)`, `$(ls ~/.gemini/config/plugins/*/scripts/diagnostics.py 2>/dev/null | head -n 1)`, and `$(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1)`) in `rules/AGENTS.md` and `skills/*/SKILL.md`.
3. Remove the migrated duplicate hooks (`json-gate`, `ast-gate`), rules (`no-error-suppression.md`, `reasoning-quality.md`), and skill (`git-worktree-sandbox`) from `~/.gemini/config/`.

### Trade-offs & Risks
- **Trade-off**: Wildcard path resolution (`~/.gemini/config/plugins/*/...`) assumes the plugin is installed in the standard Antigravity global plugins directory.
- **Mitigation**: `~/.gemini/config/plugins/` is the canonical Antigravity global plugin root across both CLI (`agy plugin install`) and Marketplace installations.

### Rejected Alternatives
- **Hardcoding `~/.gemini/config/plugins/attention-guard/`**: Rejected because Marketplace installations use a signed 64-bit hash directory name (`~/.gemini/config/plugins/<hash>/`).
