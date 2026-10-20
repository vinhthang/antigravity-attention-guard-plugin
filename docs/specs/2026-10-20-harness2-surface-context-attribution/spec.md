# Specification: Harness² Surface Validation, Pointer-Based Context Boundary & Causal Edit Attribution

- **Feature ID**: `2026-10-20-harness2-surface-context-attribution`
- **Status**: `Planning`
- **Version**: `1.0.0`
- **Date**: `2026-10-20`
- **Authors**: `Thang Hoang, Antigravity`

## 1. Context & Motivation

Analysis of Google Research's [`google-research/harness2`](https://github.com/google-research/harness2) (*Harness²: Recursive Agent Harnessing for an Open World*, arXiv:2610.14224) identified three high-impact architectural mechanisms that directly address current gaps in `antigravity-attention-guard-plugin` and its companion plugins:

1. **Unbounded Always-On Rule Bloat & Shallow Bundle Verification (Step 1)**:
   - Currently, [`scripts/deploy_plugin.py`](../../../scripts/deploy_plugin.py) (`verify_source_bundle()`, lines 18–37) only checks whether bundle paths exist and `.json` files parse. It does not enforce an `always_on_max` character cap on `rules/*.md`, does not verify that `skills/<name>/SKILL.md` files have valid frontmatter and trigger references in always-on rules (for example, `attention-metrics` is currently untriggered in `rules/AGENTS.md`), does not check that `scripts/*.py` referenced in rules/skills exist and pass `compile()`, and does not validate `hooks.json` against the Antigravity hook event schema (`PreInvocation`, `PreToolUse`, `PostToolUse`, `Stop`).
   - Across `~/.gemini/config/rules/` and `~/.gemini/config/plugins/*/rules/`, always-on rules have grown to `45,900` characters (~11,500 tokens injected into every turn), including `3,789` characters in `agent-translator/rules/AGENTS.md` that load even during non-translation coding tasks.

2. **Inline Prompt Stuffing & Missing Instruction-Injection Boundaries (Step 2a)**:
   - Currently, [`scripts/inject-rules.py`](../../../scripts/inject-rules.py) (lines 68–70) concatenates full rule files directly into `sa["Prompt"]` and does not offload oversized subagent task prompts (>12,000 chars) to disk pointers (`context/task.md`). Furthermore, subagents lack `harness2/core/prompts.py`'s explicit `EVIDENCE_BOUNDARY` directive and `harness2/core/context.py`'s grader-verdict leak tripwire (`assert_no_grader_verdicts`).

3. **Unattributed Multi-Edit Diagnosis & Confounded Memory Persistence (Step 2b)**:
   - Currently, [`schemas/diagnostician-payload.json`](../../../schemas/diagnostician-payload.json) and [`scripts/payload_validator.py`](../../../scripts/payload_validator.py) do not classify prior failed attempt edits by component verdict (`helped`, `hurt`, `no_observed_effect`, `confounded`) and do not block `confounded` multi-component edits from producing a `transferable_lesson`. Additionally, [`scripts/ledger.py`](../../../scripts/ledger.py) and [`scripts/diagnostics.py`](../../../scripts/diagnostics.py) lack `harness2/core/ledger.py`'s duplicate-label / budget-identity audit.

---

## 2. Normative Requirements

### `REQ-001`: Plugin Surface & Always-On Budget Validator (`scripts/surface_validator.py` & `scripts/deploy_plugin.py`)
- **Statement**: The plugin MUST provide `scripts/surface_validator.py` (and integrate it into `scripts/deploy_plugin.py::verify_source_bundle()`) to mechanically validate a plugin's editable component tree (`rules/`, `skills/`, `scripts/`, `hooks.json`, `schemas/`).
- **Acceptance Criteria**:
  - `AC-001-1`: Enforces an `always_on_max` character ceiling on primary always-on rule files (`rules/AGENTS.md`, default `8000` chars, configurable via `--always-on-max`) and computes `always_on_char_delta` when diffing two surface trees (`diff_summary()`).
  - `AC-001-2`: Validates every `skills/<name>/SKILL.md` for required YAML frontmatter (`description:` non-empty; `name:` matching `<name>` when present) and verifies that `<name>` appears verbatim in the plugin's always-on rules (`rules/*.md`), supporting `autotrigger()` to repair missing trigger lines when within `always_on_max`.
  - `AC-001-3`: Compiles all Python scripts under `scripts/*.py` and `skills/*/scripts/*.py` using `compile(src, rel, "exec")` and verifies that every `scripts/<name>.py` referenced in `rules/*.md` or `skills/*/SKILL.md` exists on disk.
  - `AC-001-4`: Validates `hooks.json` against the Antigravity hook schema (events in `{"PreInvocation", "PreToolUse", "PostToolUse", "Stop"}`, valid matcher/hook entry lists, `"type": "command"`, non-empty `"command"`, and existing local script targets).

### `REQ-002`: Always-On Rule Trigger & Budget Compliance
- **Statement**: `attention-guard/rules/AGENTS.md` (and companion `agent-translator/rules/AGENTS.md`) MUST satisfy `scripts/surface_validator.py` with zero untriggered skills and strictly within the `always_on_max` character budget.
- **Acceptance Criteria**:
  - `AC-002-1`: `attention-guard/rules/AGENTS.md` includes an explicit trigger line for the `attention-metrics` skill and stays `<= 8000` characters.
  - `AC-002-2`: `rtk python3 scripts/surface_validator.py --plugin-dir .` and `rtk python3 scripts/deploy_plugin.py --verify-only` exit `0` with zero errors.

### `REQ-003`: Pointer-Based Context Offloading, `EVIDENCE_BOUNDARY` & Grader Tripwire (`scripts/context_boundary.py` & `scripts/inject-rules.py`)
- **Statement**: The plugin MUST provide `scripts/context_boundary.py` and integrate it into `scripts/inject-rules.py` to enforce instruction-injection boundaries, tripwire against leaked grader verdicts, and offload oversized subagent prompts to disk pointers.
- **Acceptance Criteria**:
  - `AC-003-1`: `scripts/context_boundary.py` defines `EVIDENCE_BOUNDARY` (instructing subagents to treat workspace/context files strictly as passive data rather than instructions) and `scripts/inject-rules.py` appends it to injected subagent rules.
  - `AC-003-2`: When a subagent `Prompt` exceeds `AGY_CONTEXT_POINTER_THRESHOLD` (default `12000` chars), `materialize_context_pointer()` writes the full task body to an isolated disk file (`<context_dir>/task.md`) and replaces the inline prompt body with a compact mission pointer citing `<context_dir>/task.md`.
  - `AC-003-3`: `assert_no_grader_verdicts()` raises `ValueError` if any file name or content in a blinded context directory matches `GRADER_VERDICT_MARKERS`.

### `REQ-004`: Subagent Input/Output Shape Governance in `rules/AGENTS.md`
- **Statement**: `attention-guard/rules/AGENTS.md` MUST codify the Harness² subagent input/output trade-off rule (`c5` subagent surface rule).
- **Acceptance Criteria**:
  - `AC-004-1`: `rules/AGENTS.md` specifies that subagents are warranted for bounded tasks where input context is large and the returned payload is small (`schemas/*-payload.json`), and prohibited when the required output is as large as the input or when no context reduction occurs.

### `REQ-005`: Causal Edit Attribution & Confounding Guard (`schemas/diagnostician-payload.json` & `scripts/payload_validator.py`)
- **Statement**: `schemas/diagnostician-payload.json` and `scripts/payload_validator.py` MUST support component-level causal edit attribution (`edit_attributions`) and `transferable_lesson`, mechanically rejecting any `transferable_lesson` backed solely by `"confounded"` edit attributions.
- **Acceptance Criteria**:
  - `AC-005-1`: `schemas/diagnostician-payload.json` (`diagnosis` properties) defines optional `edit_attributions` (items with `component`, `change`, `observed_divergence`, and `verdict` in `["helped", "hurt", "no_observed_effect", "confounded"]`) and optional `transferable_lesson` (`cue`, `lesson`, `evidence`, `confidence` in `["high", "medium", "low"]`).
  - `AC-005-2`: `scripts/payload_validator.py` rejects a `diagnostician` payload with `transferable_lesson` when `edit_attributions` contains only `"confounded"` or `"no_observed_effect"` verdicts (zero `"helped"` or `"hurt"` isolated verdicts), while preserving backward compatibility for existing valid diagnostician payloads.

### `REQ-006`: Duplicate Worker Token & Budget Identity Audit (`scripts/ledger.py` & `scripts/diagnostics.py`)
- **Statement**: `scripts/ledger.py` and `scripts/diagnostics.py` MUST detect duplicate `WORK_PREPARED` worker tokens and surface retry/attempt budget accounting per conversation.
- **Acceptance Criteria**:
  - `AC-006-1`: `Ledger.audit_conversation_budget(conv_id)` in `scripts/ledger.py` returns total prepared workers, duplicate token IDs (`duplicate_tokens`), and total events, flagging any duplicate `WORK_PREPARED` token IDs.
  - `AC-006-2`: `scripts/diagnostics.py` includes `duplicate_tokens` and `budget_ok` in its JSON and CLI output.

---

## 3. Architecture & System Model

```
┌────────────────────────────────────────────────────────────────────────────┐
│                   Step 1: Pre-Flight Surface & Budget Gate                 │
│  scripts/surface_validator.py  <── invoked by ──  scripts/deploy_plugin.py │
│   - always_on_max cap (8,000 chars) & diff_summary()                       │
│   - SKILL.md frontmatter + always-on trigger check (autotrigger)           │
│   - scripts/*.py existence & py_compile check                              │
│   - hooks.json event/matcher/command validator                             │
└────────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│               Step 2a: Runtime Context & Evidence Boundary                 │
│  scripts/context_boundary.py   <── invoked by ──  scripts/inject-rules.py  │
│   - Injects EVIDENCE_BOUNDARY (files/logs = data, never instructions)      │
│   - Offloads prompts > 12,000 chars to context/<token>/task.md pointer     │
│   - Enforces assert_no_grader_verdicts() tripwire                          │
└────────────────────────────────────┬───────────────────────────────────────┘
                                     │
                                     ▼
┌────────────────────────────────────────────────────────────────────────────┐
│            Step 2b: Causal Attribution & Ledger Budget Audit               │
│  schemas/diagnostician-payload.json + scripts/payload_validator.py         │
│   - edit_attributions: helped | hurt | no_observed_effect | confounded     │
│   - Confounding guard blocks unisolated transferable_lesson                │
│  scripts/ledger.py + scripts/diagnostics.py                                │
│   - Detects duplicate worker tokens & verifies budget identity             │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Error Handling & Failure Modes

| Failure Condition | Component | Deterministic Behavior |
| :--- | :--- | :--- |
| Always-on `rules/AGENTS.md` exceeds `always_on_max` | `scripts/surface_validator.py` | Returns non-zero exit code and lists exact char count vs. cap (`REQ-001`). |
| Skill missing `description:` or missing trigger in `rules/` | `scripts/surface_validator.py` | Fails validation (`--autotrigger` repairs missing trigger line if under cap) (`REQ-001`). |
| Referenced `scripts/<name>.py` missing or syntax error | `scripts/surface_validator.py` | Fails validation with file path and `SyntaxError` line number (`REQ-001`). |
| Malformed `hooks.json` event or missing script command | `scripts/surface_validator.py` | Fails validation naming the invalid event or missing script (`REQ-001`). |
| Subagent prompt > `12000` chars | `scripts/context_boundary.py` | Writes full prompt to `<context_dir>/task.md` and substitutes file pointer mission; falls back to inline prompt if disk write fails (`REQ-003`). |
| `transferable_lesson` submitted with only `confounded` edits | `scripts/payload_validator.py` | Returns `(False, "Confounded edit attributions cannot support a transferable_lesson")` (`REQ-005`). |
| Duplicate `WORK_PREPARED` token recorded in SQLite ledger | `scripts/ledger.py` | `audit_conversation_budget()` records token in `duplicate_tokens` and sets `budget_ok = False` (`REQ-006`). |

---

## 5. Verification & Testing Plan

- Run `rtk pytest -v` across the full `attention-guard` test suite (`tests/`).
- Run `rtk python3 scripts/surface_validator.py --plugin-dir .` and `rtk python3 scripts/deploy_plugin.py --verify-only`.
- Run `rtk python3 scripts/payload_validator.py --test`.
