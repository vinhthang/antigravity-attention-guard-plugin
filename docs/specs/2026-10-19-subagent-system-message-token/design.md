# Architectural Design: Subagent Token Detection, Shell Argument Boundaries & Opus Auditor Preservation

- **Feature ID**: `2026-10-19-subagent-system-message-token`
- **Status**: `Approved`
- **Addresses**: `REQ-001`, `REQ-002`, `REQ-003`, `REQ-004`

## 1. `scripts/common.py` Changes (`REQ-001`, `REQ-003`)

### 1.1 `is_subagent()` (`REQ-001`)
```python
step = json.loads(line_str)
if step.get("type") in ("USER_INPUT", "SYSTEM_MESSAGE"):
    content = step.get("content", "")
    for match in token_pattern.finditer(content):
        tok = match.group(1)
        if tok not in tokens:
            tokens.append(tok)
```

### 1.2 `is_build_command()` Python Argument Boundary (`REQ-003`)
When `bin_name in {"python", "python3"}`:
- Iterate through `tokens[1:]`:
  - If `-m` followed by `<mod>`: return `mod.lower() == "pip"`.
  - If `arg.startswith("-m")` and `len(arg) > 2`: return `arg[2:].lower() == "pip"`.
  - If `arg == "-c"`: return `False`.
  - If `arg in {"-W", "-X", "--check-hash-based-pycs"}`: skip `i += 2`.
  - If `arg.startswith("-")`: skip `i += 1`.
  - First non-option token `<script>`: if `os.path.basename(arg).lower() == "setup.py"`, check if any remaining token in `tokens[i+1:]` is in `{"build", "install", "bdist_wheel", "sdist", "develop"}`; otherwise return `False` immediately without scanning `<script>`'s arguments.

## 2. `scripts/enforce-delegation.py` Changes (`REQ-003`)
When `bin_name in {"python", "python3"}` in `is_test_command()`:
- Iterate through `tokens[1:]`:
  - If `-m` followed by `<mod>`: return `mod.lower() in {"pytest", "unittest"}` or `mod.lower().startswith(("pytest.", "unittest."))`.
  - If `arg.startswith("-m")` and `len(arg) > 2`: return `arg[2:].lower() in {"pytest", "unittest"}`.
  - If `arg == "-c"`: return `False`.
  - If `arg in {"-W", "-X", "--check-hash-based-pycs"}`: skip `i += 2`.
  - If `arg.startswith("-")`: skip `i += 1`.
  - First non-option token `<script>`: check only `script_base = os.path.basename(arg).lower()` (`script_base in {"pytest", "pytest.py", "unittest", "unittest.py"}`) and return immediately without scanning `<script>`'s arguments!

## 3. `scripts/inject-rules.py` Changes (`REQ-004`)
In `inject-rules.py`:
- Identify traceability auditor subagents: `is_traceability_auditor = (type_name == "traceability-auditor" or "traceability" in str(sa.get("Role") or "").lower())`.
- If `is_traceability_auditor`:
  - If `str(sa.get("Model") or "").lower() in ("flash", "flash_lite")`: emit `{"decision": "deny", "reason": "Attention Guard: Traceability auditor subagent must use Opus ('pro' or 'inherit'), never 'flash'."}`.
  - If `sa.get("Model") in (None, "")`: set `sa["Model"] = "pro"`. (Preserve `"inherit"` or `"pro"`).
