# Specification: Standalone Marketplace Packaging, Modular Rule/Skill Consolidation & Portable Hook Architecture

**Feature ID**: `2026-11-05-standalone-marketplace-packaging`  
**Status**: `completed`  
**Created**: `2026-11-05`  
**Updated**: `2026-11-05`  
**Version**: `1.2.0`  
**Sign-off**: `Approved by User (2026-11-05)`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Overview & Motivation

To publish `antigravity-attention-guard-plugin` to the Google Antigravity Marketplace (`agy plugin install`) as a focused, single-purpose, zero-configuration plugin—while keeping sibling plugins (`spec-driven-plugin`, `ai-review-plugin`, `agent-translator`, `gitleaks-guard`) and unrelated skills modular and decoupled—five structural gaps must be resolved:

1. **Externalized `json-gate` Handoff Hook (`REQ-033`)**: `json-gate.py` (enforcing JSON handoff payloads and `verify_cmd` on `send_message`) currently resides in `~/.gemini/config/hooks.json` and `~/.gemini/config/scripts/` outside the plugin repository, alongside a deprecated `ast-gate.py` (500-line file read blocker) that should be retired.
2. **Fragmented Subagent/Attention Rules & Leaked Subagent Templates (`REQ-034`)**: Subagent-only prompt templates (`rules/EXECUTOR.md`, `rules/COORDINATOR.md`) sit inside `rules/`, causing the Antigravity Language Server (`GetAllPlugins`) to register them as Primary Agent rules. Meanwhile, `rules/AGENTS.md` hardcodes `/Users/thanghoang/.gemini/config/plugins/attention-guard/...` and lacks the self-contained planning approval (`explicit-approval` without hard dependency on `docs/specs/` or `ai-review-plugin`), zero-error-suppression (`no-error-suppression`), and epistemic root-cause (`reasoning-quality`) constraints needed for standalone operation.
3. **Unbundled `git-worktree-sandbox` Skill & Hardcoded Local Paths (`REQ-035`)**: Subagent workspace isolation (`git-worktree-sandbox`) sits loose in `~/.gemini/config/skills/`, and `skills/attention-metrics/SKILL.md` uses a workspace-relative path (`scripts/diagnostics.py`) that fails outside the plugin repository.
4. **Incomplete Marketplace Manifest & Missing Assets (`REQ-036`)**: `plugin.json` contains only `{"name": "attention-guard"}` (missing `displayName`, `description`, `version`, `logo`, `suggestedPrompts`, `author`, `homepage`, `repository`), lacks `assets/logo.svg` and `LICENSE`, and has untracked/dev clutter in the repository root.
5. **Local Global Config Duplication & Deprecated `ast-gate` Removal (`REQ-037`)**: Once `json-gate`, the subagent/reasoning rules, and `git-worktree-sandbox` are bundled into `attention-guard`, duplicate copies in `~/.gemini/config/` and the deprecated `ast-gate` hook must be removed while keeping other plugins and unrelated skills separate.

---

## 2. Normative Requirements

### `REQ-033` — Self-Contained `json-gate` Handoff Hook in `attention-guard` (Zero 500-Line `ast-gate` Block)
- **Description**: Bundle the JSON handoff / `verify_cmd` gate (`json-gate.py`) directly into `antigravity-attention-guard-plugin` without any 500-line file-read blocker (`ast-gate`).
- **Acceptance Criteria**:
  1. `scripts/enforce-delegation.py` (on `send_message`) and `scripts/json-gate.py` validate that `Message` is a valid JSON object (`dict`, decoding outer JSON string quotes when present), returning `"Handoff MUST be valid JSON. No conversational fluff."` on invalid JSON when `AGY_DISABLE_JSON_GATE != "1"`, and executing any optional `verify_cmd` field (`timeout=15`) with `"Verification Failed: ..."` on non-zero exit or timeout.
  2. `hooks.json` does **not** include `ast-gate` or any `read_file`/`view_file` line-count blocker.

### `REQ-034` — Consolidated Standalone `rules/AGENTS.md` ($\le 8,000$ chars) & Subagent Template Separation (`templates/`)
- **Description**: Move subagent-only templates out of `rules/` into `templates/`, and consolidate subagent/context governance (`agent-delegation`, standalone `explicit-approval` plan/subagent gating, `no-error-suppression`, and `reasoning-quality`) into a portable `rules/AGENTS.md` within the 8,000-character always-on budget, with zero hard dependency on `spec-driven-plugin` or `ai-review-plugin`.
- **Acceptance Criteria**:
  1. `rules/EXECUTOR.md` and `rules/COORDINATOR.md` are moved to `templates/EXECUTOR.md` and `templates/COORDINATOR.md`. `scripts/inject-rules.py` loads from `templates/` first with a fallback to `rules/` for backward test compatibility.
  2. `rules/` contains only `rules/AGENTS.md`, which has `<= 8000` characters (`always_on_max`), zero `/Users/thanghoang` references, zero mandatory dependency on `docs/specs/` or external review plugins, and explicit `- When ..., consult skill <name>.` trigger lines for both bundled skills (`attention-metrics` and `git-worktree-sandbox`).

### `REQ-035` — Bundle `git-worktree-sandbox` & Portable Skill Path Resolution (`skills/`)
- **Description**: Package `attention-metrics` and `git-worktree-sandbox` inside `skills/` with portable paths that work across both named directories and Marketplace hash directories.
- **Acceptance Criteria**:
  1. `skills/attention-metrics/SKILL.md` and `skills/git-worktree-sandbox/SKILL.md` (with `skills/git-worktree-sandbox/scripts/worktree_manager.py`) exist in `antigravity-attention-guard-plugin`.
  2. Zero occurrences of `/Users/thanghoang` exist across `rules/`, `templates/`, `skills/`, `scripts/`, and `hooks.json`.
  3. Skill command invocations in `skills/*/SKILL.md` and `rules/AGENTS.md` use portable plugin path discovery (`~/.gemini/config/plugins/*/...`) that works both in named directories (`attention-guard`) and Marketplace hash directories (`<signed-int64-hash>`).

### `REQ-036` — Marketplace Manifest (`plugin.json`), Brand Assets (`assets/logo.svg`), `LICENSE` & Repository Hygiene
- **Description**: Complete `plugin.json` per the Antigravity Plugin Loader specification, add `assets/logo.svg` and `LICENSE`, and clean repository root artifacts.
- **Acceptance Criteria**:
  1. `plugin.json` defines `name` (`"attention-guard"`), `displayName` (`"Attention Guard"`), `version` (`"1.0.0"`), `description`, `logo` (`"assets/logo.svg"`), `author`, `homepage`, `repository`, and `suggestedPrompts` (3 items), using only supported top-level loader keys.
  2. `assets/logo.svg` exists (valid square SVG $\ge 128\times 128$ with transparent background and $\ge 10\%$ margin) and `LICENSE` (MIT) exists at the repository root.
  3. `.gitignore` excludes `.coverage`, `review.json`, `review.md`, `.codegraph/`, `.code-review/`, and `.worktrees/`, and legacy root scratch files (`task.md`, `REVERIFICATION_REPORT.md`, `review.json`, `.coverage`) are removed from the working tree/index.

### `REQ-037` — Local Global Config Deduplication (`~/.gemini/config/`), `ast-gate` Removal & Ecosystem Verification
- **Description**: Remove the deprecated `ast-gate` hook and migrated duplicates (`json-gate`, `no-error-suppression.md`, `reasoning-quality.md`, `git-worktree-sandbox`) from `~/.gemini/config/` while preserving all other plugins, rules, and skills, and verify full CLI/test/audit compliance.
- **Acceptance Criteria**:
  1. `~/.gemini/config/hooks.json` removes both `json-gate` and the deprecated `ast-gate` (and `~/.gemini/config/scripts/{json-gate.py,ast-gate.py,implementation_plan.md}` are removed); `~/.gemini/config/skills/ast-grep-toolkit/SKILL.md` is updated to remove deprecated `ast-gate.py` / 500-line blocker references; and `~/.gemini/config/skills/git-worktree-sandbox` plus `~/.gemini/config/rules/{no-error-suppression.md,reasoning-quality.md}` are removed since they are now provided by `attention-guard`.
  2. `rtk agy plugin validate .` exits `0` reporting `2` skills processed and `2` hooks processed; `rtk python3 scripts/system_audit.py` exits `0` (`Overall Valid: True`); and `rtk pytest tests/` passes with `0` failures.
