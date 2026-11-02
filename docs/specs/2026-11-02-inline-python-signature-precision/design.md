# Technical Design: Precision Inline `python -c` Polling Signature Normalization

## 1. Architectural Mapping to Requirements

| Component | File(s) | Requirement IDs |
|---|---|---|
| Antigravity Command Signature Normalizer | `scripts/enforce-delegation.py` | `Addresses: REQ-030` |
| DeepSeek Harness Command Signature Normalizer | `/Users/thanghoang/github/dsh-attention-guard-plugin/src/circuit-breaker.ts` | `Addresses: REQ-030` |
| Unit & Regression Tests | `tests/test_ledger_performance.py`, `/Users/thanghoang/github/dsh-attention-guard-plugin/tests/circuit-breaker.spec.ts` | `Addresses: REQ-030` |

---

## 2. Detailed Component Design (`REQ-030`, `ADR-001`)

### 2.1 `scripts/enforce-delegation.py` (`normalize_command_signature`)

Replace lines 298–306 of `scripts/enforce-delegation.py` with:
```python
    # Check python -c reading/tailing a file directly without analytical logic (REQ-030, ADR-001)
    if re.search(r"\bpython[0-9.]*\s+-c\b", c):
        is_write = any(w in c for w in ('"w"', "'w'", '"a"', "'a'", '"w+"', "'w+'", 'write_text', 'write_bytes'))
        has_analysis = bool(
            re.search(
                r"\b(?:import\s+(?:re|json|xml|ast|difflib|csv|sqlite3|collections)|re\.|json\.|difflib\.|ET\.|def\s+\w+|for\s+\w+\s+in\b)",
                c,
            )
        )
        if not is_write and not has_analysis:
            m_open = re.search(
                r"(?:open|Path)\s*\(\s*['\"]([^'\"]+)['\"][^)]*\)\s*\.\s*(?:readlines|read_text|read|readline)\b",
                c,
            )
            if m_open:
                file_path = m_open.group(1).strip()
                return f"POLL_FILE:{os.path.normpath(file_path)}"
```

### 2.2 `/Users/thanghoang/github/dsh-attention-guard-plugin/src/circuit-breaker.ts` (`normalizeCommandSignature`)

Update the `python -c` branch in `normalizeCommandSignature(cmd: string)` to apply the identical guard:
- Check `hasAnalysis = /\b(?:import\s+(?:re|json|xml|ast|difflib|csv|sqlite3|collections)|re\.|json\.|difflib\.|ET\.|def\s+\w+|for\s+\w+\s+in\b)/.test(c)`.
- Require direct method chaining `/(?:open|Path)\s*\(\s*['"]([^'"]+)['"][^)]*\)\s*\.\s*(?:readlines|read_text|read|readline)\b/` when `!isWrite && !hasAnalysis`.

### 2.3 Verification & Regression Testing (`tests/test_ledger_performance.py`, `tests/circuit-breaker.spec.ts`)

Add unit tests verifying:
1. Direct file-polling one-liners (`open('/tmp/a.log').readlines()[-26:]`, `Path('/tmp/a.log').read_text().splitlines()[-10:]`) normalize to `POLL_FILE:/tmp/a.log`.
2. Directory `Path('/Users/thanghoang/github/books/runs/trang_tu')` scripts with `for` loops or `json`/`re`/`xml` imports do **not** collapse to `POLL_FILE:...`.
3. Three distinct analytical `python3 -c` scripts inspecting `VietnameseDictionary.swift` execute consecutively without triggering `check_subagent_doom_loop()`.
4. Three identical analytical `python3 -c` scripts still trigger `check_subagent_doom_loop()` on the 3rd consecutive execution.
