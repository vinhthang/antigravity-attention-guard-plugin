# Specification: Precision Inline `python -c` Polling Signature Normalization

**Feature ID**: `2026-11-02-inline-python-signature-precision`  
**Status**: `completed`  
**Created**: `2026-11-02`  
**Version**: `1.0.0`  
**Sign-off**: `Approved by User ("Yes, proceed")`  
**Precedence**: `spec.md` > `decisions.md` > `design.md` > `tasks.md`

---

## 1. Problem Statement & Telemetry Evidence

Telemetry from `~/.gemini/antigravity/attention_guard.db` (`2026-10-26` to `2026-11-02`) revealed **20 false-positive `PRIMARY_TOOL_DENIED` blocks** (7 last week and 13 on `2026-11-02` across conversations `40750985`, `4754d091`, `97919bb1`, `04f1565d`, `9fb90a28`, `d8e89a6d`, `0e7710d1`, and `560b98d5`) caused by over-broad inline `python -c` matching in `normalize_command_signature()` (`scripts/enforce-delegation.py`) and `normalizeCommandSignature()` (`dsh-attention-guard-plugin/src/circuit-breaker.ts`):

1. **Multi-File / Directory `Path(...)` Collapse**:
   - Subagents running distinct multi-line `python3 -c` verification scripts that began with `run_dir = Path("/Users/thanghoang/github/books/runs/trang_tu")` and later called `(run_dir / ch_id / "final.txt").read_text()` matched `re.search(r"(?:open|Path)\s*\(\s*['\"]([^'\"]+)['\"]", c)` on the top-level directory `Path(...)` literal.
   - Consequently, 3 completely different verification scripts in the same workspace were collapsed into `POLL_FILE:/Users/thanghoang/github/books/runs/trang_tu` and blocked on the 3rd execution.
2. **Distinct Analytical Queries on Large Files (>500 Lines)**:
   - When a file exceeds 500 lines (`ast-gate.py` blocks full `read_file`), subagents legitimately run distinct `python3 -c` inspection snippets (`import re`, `import json`, `import xml.etree.ElementTree`, `import difflib`, `for ... in ...`, `def ...`) on the same file (`Sources/OpenKey/macOS-Swift/Sources/OpenKeySwiftCore/VietnameseDictionary.swift`).
   - Collapsing distinct analytical scripts into `POLL_FILE:<path>` falsely triggered the Subagent Doom-Loop Circuit Breaker even though each command executed different logic.

---

## 2. Normative Requirements (EARS Syntax)

### `REQ-030` — Precision Inline `python -c` File-Polling Normalization (`ADR-001`)
- **WHEN** `normalize_command_signature()` in `scripts/enforce-delegation.py` (and `normalizeCommandSignature()` in `/Users/thanghoang/github/dsh-attention-guard-plugin/src/circuit-breaker.ts`) evaluates a `python` / `python3` `-c` command, **THE** normalizer **SHALL** collapse the command to `POLL_FILE:<normalized_path>` **only** when the inline script is a direct, non-analytical file-read/tail one-liner (where `open('<path>')` or `Path('<path>')` is directly chained to `.readlines()`, `.read_text()`, `.read()`, or `.readline()` without analytical modules or control-flow constructs such as `import re`, `import json`, `import xml`, `import ast`, `import difflib`, `re.`, `json.`, `difflib.`, `ET.`, `def `, or `for ... in`), preserving the full command string as the signature for distinct analytical `python -c` scripts.
- **Acceptance Criteria**:
  - Direct file-polling one-liners such as `rtk python3 -c "open('/tmp/a.log').readlines()[-26:]"` and `rtk python3 -c "Path('/tmp/a.log').read_text().splitlines()[-20:]"` continue to normalize to `POLL_FILE:/tmp/a.log`.
  - Multi-line or analytical `python3 -c` scripts that construct a directory `Path('/Users/thanghoang/github/books/runs/trang_tu')` and read child files in a `for` loop or with `re`/`json`/`xml`/`difflib` are **not** collapsed to `POLL_FILE:...` and retain their distinct command signatures.
  - Three consecutive `python3 -c` commands executing **different** analytical queries (`import re`, `for i, line in enumerate(...)`, etc.) against the same source file (`VietnameseDictionary.swift`) are **allowed** without triggering `check_subagent_doom_loop()`.
  - Three consecutive executions of the **exact same** analytical `python3 -c` script still trigger `check_subagent_doom_loop()` on the 3rd consecutive execution.
