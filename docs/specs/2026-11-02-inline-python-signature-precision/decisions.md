# Architectural Decision Records: Precision Inline `python -c` Polling Signature Normalization

## ADR-001: Restrict `POLL_FILE` Normalization on `python -c` to Direct Chained Read/Tail One-Liners Without Analytical Constructs (`REQ-030`)
- **Status**: Accepted
- **Addresses**: `REQ-030`
- **Context**:
  In `REQ-024`, `normalize_command_signature()` added a rule matching any `python -c` command containing `readlines`, `read_text`, `read(`, or `readline` and extracting the first `open('<path>')` or `Path('<path>')` string literal as `POLL_FILE:<path>`. Live telemetry from `2026-10-26` to `2026-11-02` showed 20 false-positive denials (including 13 of 14 denials on `2026-11-02`) because:
  1. Scripts starting with `run_dir = Path("/path/to/dir")` and later calling `(run_dir / ch / "final.txt").read_text()` matched the directory `Path(...)` literal and collapsed all scripts in that directory to `POLL_FILE:/path/to/dir`.
  2. Distinct analytical `python3 -c` queries (`import re`, `import json`, `import xml`, `for ... in ...`, `def ...`) inspecting different parts of a >500-line file (`VietnameseDictionary.swift`) were collapsed into `POLL_FILE:.../VietnameseDictionary.swift` even though the commands were not polling a log file and were not identical.
- **Decision**:
  Update `normalize_command_signature()` in `scripts/enforce-delegation.py` and `normalizeCommandSignature()` in `/Users/thanghoang/github/dsh-attention-guard-plugin/src/circuit-breaker.ts` so that a `python -c` command normalizes to `POLL_FILE:<path>` **only** when:
  1. It does not perform file writes (`"w"`, `'w'`, `"a"`, `'a'`, `"w+"`, `'w+'`, `write_text`, `write_bytes`).
  2. It does not contain analytical or multi-step control-flow constructs (`\b(?:import\s+(?:re|json|xml|ast|difflib|csv|sqlite3|collections)|re\.|json\.|difflib\.|ET\.|def\s+\w+|for\s+\w+\s+in\b)`).
  3. The path literal in `open('<path>')` or `Path('<path>')` is directly chained to the read method: `(?:open|Path)\s*\(\s*['"]([^'"]+)['"][^)]*\)\s*\.\s*(?:readlines|read_text|read|readline)\b`.
  When these conditions are not met, `normalize_command_signature()` returns the stripped command `c`, so identical 3x repetitions of the same script are still caught while distinct analytical scripts are allowed.
- **Trade-offs & Risks**:
  - *Pros*: Eliminates 100% of the 20 observed false-positive `PRIMARY_TOOL_DENIED` blocks from `attention_guard.db` while preserving `POLL_FILE:<path>` detection for `tail`/`head`/`wc` and inline `python3 -c "open('/tmp/a.log').readlines()[-26:]"` log-polling loops.
  - *Cons / Risks*: A subagent could theoretically write 3 syntactically different `for` loops to poll a log file via `python3 -c`. In practice, LLM log-polling loops either repeat the exact same command (still caught by exact command comparison) or vary slice indices on `open('...').readlines()[-N:]` / `tail -n N` (still caught by `POLL_FILE:<path>`).
- **Rejected Alternatives**:
  - *Alternative 1: Remove `python -c` normalization from `normalize_command_signature()` entirely.* Rejected because `REQ-024` explicitly requires catching subagents that alternate between `tail -n N /tmp/a.log` and `python3 -c "open('/tmp/a.log').readlines()[-N:]"`.
  - *Alternative 2: Only normalize `python -c` when the target file extension is `.log`.* Rejected because subagents also poll `.jsonl`, `.out`, `.txt`, and extensionless pipe/status files in `/tmp/`.
