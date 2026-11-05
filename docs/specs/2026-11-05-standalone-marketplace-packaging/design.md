# Architecture & Implementation Design: Standalone Marketplace Packaging

**Feature ID**: `2026-11-05-standalone-marketplace-packaging`  
**Status**: `draft`

---

## 1. Component Map & Traceability Matrix

| Requirement | Target Files | Architectural Change |
|---|---|---|
| `REQ-033` (`ADR-001`) | `scripts/json-gate.py`, `scripts/enforce-delegation.py` | Bundle `scripts/json-gate.py` and enforce JSON `dict` + `verify_cmd` check on `send_message` in `scripts/enforce-delegation.py` (without any 500-line `ast-gate` hook). |
| `REQ-034` (`ADR-002`) | `rules/AGENTS.md`, `templates/EXECUTOR.md`, `templates/COORDINATOR.md`, `scripts/inject-rules.py` | Move `EXECUTOR.md` and `COORDINATOR.md` from `rules/` to `templates/`; update `inject-rules.py` to resolve `templates/` with fallback to `rules/`; author consolidated `rules/AGENTS.md` ($\le 8,000$ chars) integrating `agent-delegation`, standalone plan/subagent approval gating, `no-error-suppression`, and `reasoning-quality` plus autotrigger lines for `attention-metrics` and `git-worktree-sandbox`. |
| `REQ-035` (`ADR-003`) | `skills/attention-metrics/SKILL.md`, `skills/git-worktree-sandbox/SKILL.md`, `skills/git-worktree-sandbox/scripts/worktree_manager.py` | Bundle `git-worktree-sandbox` into `skills/`, remove `/Users/thanghoang` references, and update `SKILL.md` commands to portable `~/.gemini/config/plugins/*/` paths. |
| `REQ-036` (`ADR-003`) | `plugin.json`, `assets/logo.svg`, `LICENSE`, `.gitignore`, `README.md` | Populate `plugin.json` with full Marketplace metadata, create `assets/logo.svg` and MIT `LICENSE`, update `.gitignore`, and delete root scratch files (`task.md`, `REVERIFICATION_REPORT.md`, `review.json`, `.coverage`). |
| `REQ-037` (`ADR-001`, `ADR-003`) | `~/.gemini/config/hooks.json`, `~/.gemini/config/rules/`, `~/.gemini/config/skills/`, `~/.gemini/config/scripts/`, `tests/` | Remove deprecated `ast-gate` and migrated duplicates (`json-gate`, `no-error-suppression.md`, `reasoning-quality.md`, `git-worktree-sandbox`) from `~/.gemini/config/`, strip `ast-gate` references from `~/.gemini/config/skills/ast-grep-toolkit/SKILL.md`, and add unit/integration tests. |

---

## 2. Detailed Design

### 2.1 Self-Contained `json-gate` in `enforce-delegation.py` (`REQ-033`)
- `scripts/enforce-delegation.py`:
  - Whenever `tool_name in ["send_message", "default_api:send_message"]` (for both Primary Agent and Subagent), if `os.environ.get("AGY_DISABLE_JSON_GATE") != "1"`, verify that the decoded `Message` is a valid JSON `dict`. If not, call `emit_deny("Handoff MUST be valid JSON. No conversational fluff.")`.
  - If `parsed_msg.get("verify_cmd")` is present, execute `subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, timeout=15)` and call `emit_deny(f"Verification Failed: {err_output}")` if `returncode != 0` or timeout occurs.
- `scripts/json-gate.py` is also included in `scripts/` for standalone CLI/hook compatibility.

### 2.2 `templates/` Resolution & Consolidated `rules/AGENTS.md` (`REQ-034`)
- `scripts/inject-rules.py` resolves `templates/EXECUTOR.md` and `templates/COORDINATOR.md` relative to `os.path.dirname(__file__)`, falling back to `rules/EXECUTOR.md` and `rules/COORDINATOR.md` if `templates/` does not exist in a test fixture.
- `rules/AGENTS.md` is structured under `8,000` characters (`~6,500` chars) with 4 sections:
  1. **Attention Protection, Planning Gate & Subagent Delegation** (`agent-delegation` + standalone Phase 0 `/grill-me` disambiguation & Phase 1 `/plan` `implementation_plan.md` human `"Proceed"` approval gate before Phase 2 subagent dispatch)
  2. **Subagent Lifecycle, 300s Watchdog & JSON Data Contracts**
  3. **Problem Intolerance, Zero Error Suppression & Epistemic Honesty** (`no-error-suppression` + `reasoning-quality`: zero silent failures, zero speculative trial-and-error edits without verified root cause, zero capability substitution)
  4. **Skill Routing Triggers** (explicit `- When ..., consult skill <name>.` lines for `attention-metrics` and `git-worktree-sandbox`).

### 2.3 Portable Skill & Script Discovery (`REQ-035`)
- Because Marketplace installations use `~/.gemini/config/plugins/<signed-int64-hash>/`, commands in `rules/AGENTS.md` and `skills/*/SKILL.md` use:
  - `python3 $(ls ~/.gemini/config/plugins/*/scripts/payload_validator.py 2>/dev/null | head -n 1) --role <executor|diagnostician|coordinator> --payload '<json>'`
  - `python3 $(ls ~/.gemini/config/plugins/*/scripts/diagnostics.py 2>/dev/null | head -n 1) --metrics --json`
  - `python3 $(ls ~/.gemini/config/plugins/*/skills/git-worktree-sandbox/scripts/worktree_manager.py 2>/dev/null | head -n 1) ...`

### 2.4 Marketplace Manifest & Brand Assets (`REQ-036`)
- `plugin.json` includes `name`, `displayName`, `version`, `description`, `logo` (`"assets/logo.svg"`), `author`, `homepage`, `repository`, and `suggestedPrompts` (3 items).
- `assets/logo.svg` is a `256x256` SVG shield/lens emblem with a `10%` transparent margin (`26px` padding around a `204x204` graphic) and high-contrast cyan/indigo gradients visible on both light and dark themes.
