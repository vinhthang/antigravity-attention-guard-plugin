#!/usr/bin/env python3
import sys, os, json, shlex, re, time, uuid
from typing import Optional, Dict, Any, List, Tuple
sys.path.insert(0, os.path.dirname(__file__))
from common import (
    is_subagent,
    get_turn_state,
    get_primary_model,
    is_thinking_model,
    is_markdown_file,
    is_build_command,
    parse_transcript,
)
from ledger import Ledger
from fsm import Event

MUTATION_TOOLS = {
    "write_to_file", "default_api:write_to_file",
    "replace_file_content", "default_api:replace_file_content",
    "multi_replace_file_content", "default_api:multi_replace_file_content",
    "write_file", "default_api:write_file",
    "edit_file", "default_api:edit_file",
}

TEST_TAMPER_PATTERNS = [
    "@pytest.mark.skip",
    "@pytest.mark.xfail",
    "@unittest.skip",
    "pytest.skip(",
    "pytest.xfail(",
    "it.skip(",
    "describe.skip(",
    "test.skip(",
    "t.Skip(",
    "assert True",
]

def _extract_target_file(args: dict) -> str:
    if not isinstance(args, dict):
        return ""
    return str(
        args.get("Path")
        or args.get("TargetFile")
        or args.get("target_file")
        or args.get("file_path")
        or args.get("path")
        or ""
    )

extract_target_file = _extract_target_file

def is_test_file(target_file: str) -> bool:
    if not target_file or not isinstance(target_file, str):
        return False
    norm = target_file.replace("\\", "/").lower()
    base = os.path.basename(norm)
    if "/tests/" in norm or norm.startswith("tests/") or "/test/" in norm:
        return True
    if (base.startswith("test_") and base.endswith(".py")) or base.endswith("_test.py"):
        return True
    if base.endswith((
        ".test.ts", ".spec.ts", ".test.tsx", ".spec.tsx",
        ".test.js", ".spec.js", ".test.jsx", ".spec.jsx",
        ".test.mjs", ".spec.mjs", ".test.cjs", ".spec.cjs",
        "_test.go"
    )):
        return True
    return False

def _strip_quotes_and_comments(line: str, lang_ext: str) -> str:
    # 1. Replace strings with placeholders
    if lang_ext == "ts":
        line = re.sub(r'`(?:\\.|[^`\\])*`', '""', line)
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)

    # 2. Strip comments
    if lang_ext == "py":
        line = re.sub(r'#.*$', '', line)
    elif lang_ext in ("ts", "go"):
        line = re.sub(r'//.*$', '', line)
        line = re.sub(r'/\*.*?\*/', '', line)

    return line

def check_test_tampering(target_file: str, args: dict) -> Optional[str]:
    if os.environ.get("AGY_ALLOW_TEST_SKIP") == "1":
        return None
    if not target_file or not is_test_file(target_file):
        return None
    if not isinstance(args, dict):
        return None

    target = str(args.get("Target") or args.get("TargetContent") or "")
    replacement = str(
        args.get("Replacement")
        or args.get("ReplacementContent")
        or args.get("Content")
        or args.get("CodeContent")
        or ""
    )

    if "ReplacementChunks" in args and isinstance(args.get("ReplacementChunks"), list):
        for chunk in args.get("ReplacementChunks", []):
            if isinstance(chunk, dict):
                target += "\n" + str(chunk.get("Target") or chunk.get("TargetContent") or "")
                replacement += "\n" + str(chunk.get("Replacement") or chunk.get("ReplacementContent") or "")

    lower_target = target_file.lower()
    if lower_target.endswith(".py"):
        lang_ext = "py"
        patterns = [
            "@pytest.mark.skip",
            "@pytest.mark.xfail",
            "@unittest.skip",
            "pytest.skip(",
            "pytest.xfail(",
            "assert True",
        ]
    elif any(lower_target.endswith(e) for e in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")):
        lang_ext = "ts"
        patterns = [
            "it.skip(",
            "describe.skip(",
            "test.skip(",
        ]
    elif lower_target.endswith(".go"):
        lang_ext = "go"
        patterns = [
            "t.Skip(",
        ]
    else:
        lang_ext = "other"
        patterns = TEST_TAMPER_PATTERNS

    target_lines = set(target.splitlines())
    clean_replacement = replacement
    if lang_ext == "py":
        clean_replacement = re.sub(r'"""[\s\S]*?"""', '""', clean_replacement)
        clean_replacement = re.sub(r"'''[\s\S]*?'''", "''", clean_replacement)
    elif lang_ext == "ts":
        clean_replacement = re.sub(r'`[\s\S]*?`', '""', clean_replacement)
        clean_replacement = re.sub(r'/\*[\s\S]*?\*/', '', clean_replacement)

    for line in clean_replacement.splitlines():
        if line in target_lines:
            continue
        clean_line = _strip_quotes_and_comments(line, lang_ext)
        for pattern in patterns:
            matched = False
            if pattern == "assert True":
                if re.search(r"\bassert\s+True\b", clean_line):
                    matched = True
            else:
                if pattern in clean_line:
                    matched = True
            if matched:
                return (
                    f"Attention Guard: Test tampering detected. Introducing test-skipping marker or bypass "
                    f"'{pattern}' in test file '{target_file}' is forbidden."
                )
    return None

def check_destructive_command(cmd_str: str) -> Optional[str]:
    if not cmd_str or not isinstance(cmd_str, str):
        return None
    # REQ-026: Normalize POSIX backslash-newline line continuations before splitting
    clean_cmd = re.sub(r"\\\r?\n", " ", cmd_str)
    sub_cmds = re.split(r"[;&|]+", clean_cmd)
    for sub in sub_cmds:
        s = sub.strip()
        if not s:
            continue
        try:
            tokens = shlex.split(s)
        except Exception:
            tokens = s.split()
        while tokens and tokens[0] in ("rtk", "sudo"):
            tokens.pop(0)
        if not tokens:
            continue

        bin_name = tokens[0]
        if bin_name == "git" and len(tokens) > 1:
            subcmd = tokens[1]
            if subcmd == "reset" and any(t == "--hard" or t.startswith("--hard=") for t in tokens[2:]):
                return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (git reset --hard)."
            if subcmd == "clean":
                for t in tokens[2:]:
                    if t.startswith("-") and not t == "--":
                        if "f" in t or "F" in t:
                            return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (git clean -f)."
            if subcmd == "checkout":
                if any(t == "." for t in tokens[2:]):
                    return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (git checkout .)."
            if subcmd == "restore":
                if any(t == "." for t in tokens[2:]):
                    return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (git restore .)."
            if subcmd == "push":
                has_lease = any("--force-with-lease" in t for t in tokens[2:])
                has_force = any(t in ("--force", "-f") or (t.startswith("-") and not t.startswith("--") and "f" in t) for t in tokens[2:])
                if has_force and not has_lease:
                    return f"Attention Guard: Destructive command '{cmd_str}' is forbidden (git push --force without --force-with-lease)."

        if bin_name == "rm":
            is_recursive = False
            targets = []
            for t in tokens[1:]:
                if t.startswith("-") and not t == "--":
                    if "r" in t or "R" in t:
                        is_recursive = True
                else:
                    if t != "--":
                        targets.append(t)
            if is_recursive:
                catastrophic = {"/", "~", "$HOME", "${HOME}", ".", "..", ".git", "./.git", "/.git"}
                for tgt in targets:
                    norm = tgt.rstrip("/").strip()
                    if norm in catastrophic or tgt in catastrophic:
                        return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (catastrophic rm targeting '{tgt}')."
                    if norm == "":
                        # Only reject if the original command explicitly passed an empty quoted argument ("" or '')
                        if tgt == "" and any(q in s for q in ('""', "''")):
                            return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (catastrophic rm targeting '{tgt}')."
    return None

def record_subagent_file_edit(conv_id: str, target_file: str = "", ledger: Optional[Ledger] = None):
    if ledger is None:
        ledger = Ledger()
    now = time.time()
    event_id = f"{conv_id}_subagent_file_edit_{now}_{uuid.uuid4().hex[:8]}"
    try:
        with ledger._get_connection() as conn:
            conn.execute(
                "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                (event_id, "SUBAGENT_FILE_EDIT", json.dumps({"target_file": target_file}), now)
            )
    except Exception as exc:
        sys.stderr.write(f"Warning in record_subagent_file_edit: {exc}\n")

def normalize_command_signature(cmd: str) -> str:
    if not cmd or not isinstance(cmd, str):
        return ""
    c = cmd.strip()
    # Strip leading rtk / sudo prefixes
    while True:
        prev = c
        c = re.sub(r"^(?:rtk\s+proxy\s+|rtk\s+|sudo\s+)", "", c).strip()
        if c == prev:
            break

    # Strip sleep chained before command (e.g. sleep 2 && ...)
    c = re.sub(r"^(?:rtk\s+)?sleep\s+\d+\s*&&\s*", "", c).strip()

    # Re-strip rtk / sudo if sleep was preceding
    while True:
        prev = c
        c = re.sub(r"^(?:rtk\s+proxy\s+|rtk\s+|sudo\s+)", "", c).strip()
        if c == prev:
            break

    # 1. Process-Polling Signature (POLL_PROC:<target>)
    # Check pgrep: e.g. pgrep -P 59170 -l, pgrep -fl -P 59170, pgrep my_proc
    if c.startswith("pgrep") or re.search(r"\bpgrep\b", c):
        m_pid = re.search(r"-[pP]\s*(\d+)", c)
        if m_pid:
            return f"POLL_PROC:{m_pid.group(1)}"
        m_target = re.search(r"\bpgrep\b(?:\s+-[a-zA-Z0-9]+)*\s+([^\s|&;]+)", c)
        if m_target:
            target = m_target.group(1).strip()
            if target:
                return f"POLL_PROC:{target}"

    # Check ps: e.g. ps -p 59170 -o pid,comm or ps -ef | grep 59170
    if c.startswith("ps ") or c == "ps" or re.search(r"\bps\b", c):
        m_grep = re.search(r"\|\s*(?:rtk\s+)?grep\b(?:\s+-[a-zA-Z0-9]+)*\s+['\"]?([^'\"\s|&;]+)", c)
        if m_grep:
            grep_target = m_grep.group(1).strip()
            if grep_target:
                return f"POLL_PROC:{grep_target}"
        m_pid = re.search(r"-[pP]\s*(\d+)", c)
        if m_pid:
            return f"POLL_PROC:{m_pid.group(1)}"

    # 2. File-Polling Signature (POLL_FILE:<path>)
    # Check tail, head, wc: e.g. tail -n 25 /tmp/a.log, wc -l /tmp/a.log
    m_cmd = re.match(r"^(?:tail|head|wc)\b", c)
    if m_cmd:
        try:
            tokens = shlex.split(c)
        except Exception:
            tokens = c.split()
        file_candidates = [t for t in tokens[1:] if not t.startswith("-") and not t.isdigit()]
        if file_candidates:
            file_path = file_candidates[-1]
            return f"POLL_FILE:{os.path.normpath(file_path)}"

    # Check python -c reading/tailing a file directly without analytical logic (REQ-030, ADR-001)
    if re.search(r"\bpython[0-9.]*\s+-c\b", c):
        is_write = any(w in c for w in ('"w"', "'w'", '"a"', "'a'", '"w+"', "'w+'", 'write_text', 'write_bytes'))
        has_analysis = bool(
            re.search(
                r"\b(?:import\s+(?:re|json|xml|ast|difflib|csv|sqlite3|collections)|re\.|json\.|difflib\.|ET\.|def\s+\w+|for\s+[\w,\s()]+\s+in\b)",
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

    return c

def check_subagent_doom_loop(*args, **kwargs) -> Optional[str]:
    """Check for subagent doom loop on consecutive identical run_command executions."""
    ledger = None
    conv_id = "unknown"
    turn_id = "unknown"
    tool_name = "run_command"
    tool_args = {}
    threshold = kwargs.get("threshold", 3)

    if args and isinstance(args[0], Ledger):
        ledger = args[0]
        if len(args) > 1: conv_id = str(args[1])
        if len(args) > 2: turn_id = str(args[2])
        if len(args) > 3: tool_name = str(args[3])
        if len(args) > 4: tool_args = args[4]
    elif args and isinstance(args[0], str):
        conv_id = args[0]
        if len(args) > 1:
            if isinstance(args[1], dict):
                tool_args = args[1]
            else:
                tool_args = {"CommandLine": str(args[1])}
        if len(args) > 2 and isinstance(args[2], int):
            threshold = args[2]
        ledger = kwargs.get("ledger") or (args[3] if len(args) > 3 and isinstance(args[3], Ledger) else None)

    if ledger is None:
        ledger = Ledger()

    if tool_name in MUTATION_TOOLS:
        target = _extract_target_file(tool_args) if isinstance(tool_args, dict) else str(tool_args)
        record_subagent_file_edit(conv_id, target, ledger)
        return None

    if tool_name not in ("run_command", "default_api:run_command"):
        return None

    cmd = tool_args.get("CommandLine", "") if isinstance(tool_args, dict) else str(tool_args)
    cmd_norm = cmd.strip()
    if not cmd_norm:
        return None

    try:
        with ledger._get_connection() as conn:
            rows = conn.execute(
                "SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at DESC",
                (f"{conv_id}_%",)
            ).fetchall()

        identical_count = 0
        cmd_sig = normalize_command_signature(cmd_norm)
        for row in rows:
            etype = row["type"]
            if etype == "SUBAGENT_FILE_EDIT":
                break
            if etype == "SUBAGENT_COMMAND":
                payload_str = row["payload"]
                try:
                    pdata = json.loads(payload_str)
                    recorded_cmd = pdata.get("command", "") if isinstance(pdata, dict) else str(pdata)
                except Exception:
                    recorded_cmd = str(payload_str)
                if normalize_command_signature(recorded_cmd) == cmd_sig:
                    identical_count += 1
                else:
                    break

        if identical_count >= (threshold - 1):
            return (
                f"Attention Guard: Subagent doom-loop circuit breaker. "
                f"Command '{cmd_norm}' executed {identical_count + 1} times consecutively without intervening file edits. "
                f"Do not poll processes or logs in a shell loop; return your current status or await async completion."
            )

        now = time.time()
        event_id = f"{conv_id}_subagent_cmd_{now}_{uuid.uuid4().hex[:8]}"
        with ledger._get_connection() as conn:
            conn.execute(
                "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                (event_id, "SUBAGENT_COMMAND", json.dumps({"command": cmd_norm}), now)
            )
    except Exception as exc:
        sys.stderr.write(f"Warning in check_subagent_doom_loop: {exc}\n")

    return None

def is_artifact_path(target_file, artifact_dir):
    if not target_file: return False
    norm_target = os.path.realpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.realpath(os.path.abspath(artifact_dir))
        try:
            if os.path.commonpath([norm_target, norm_artifact]) == norm_artifact:
                return True
        except ValueError as exc:
            sys.stderr.write(f"Warning in is_artifact_path: {exc}\n")

    app_data_dir = os.path.realpath(os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity"))
    brain_dir = os.path.join(app_data_dir, "brain")
    try:
        if os.path.commonpath([norm_target, brain_dir]) == brain_dir:
            return True
    except ValueError as exc:
        sys.stderr.write(f"Warning in is_artifact_path: {exc}\n")

    return False

def is_test_command(cmd_str):
    if not cmd_str or not isinstance(cmd_str, str):
        return False
    try:
        tokens = shlex.split(cmd_str)
    except Exception:
        tokens = cmd_str.split()
    while tokens and tokens[0] == "rtk":
        tokens.pop(0)
    if not tokens:
        return False

    bin_name = os.path.basename(tokens[0]).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if bin_name.endswith(ext):
            bin_name = bin_name[:-len(ext)]
            break

    # Direct test runners
    if bin_name in {"pytest", "vitest", "jest", "mocha", "ctest", "ava"}:
        return True

    # Python running pytest or unittest
    if bin_name in {"python", "python3"}:
        i = 1
        while i < len(tokens):
            arg = tokens[i]
            if arg == "-m":
                if i + 1 < len(tokens):
                    mod = tokens[i + 1].lower()
                    return mod in {"pytest", "unittest"} or mod.startswith(("pytest.", "unittest."))
                return False
            if arg.startswith("-m") and len(arg) > 2:
                mod = arg[2:].lower()
                return mod in {"pytest", "unittest"} or mod.startswith(("pytest.", "unittest."))
            if arg == "-c":
                return False
            if arg in {"-W", "-X", "--check-hash-based-pycs"}:
                i += 2
                continue
            if arg.startswith("-"):
                i += 1
                continue
            # First non-option positional argument (<script>)
            script_base = os.path.basename(arg).lower()
            return script_base in {"pytest", "pytest.py", "unittest", "unittest.py"}
        return False

    # Package managers / build tools with 'test' subcommand
    if bin_name in {"cargo", "go", "npm", "pnpm", "yarn", "bun", "dotnet"}:
        if any(t == "test" for t in tokens[1:]):
            return True

    # Java build tools (mvn test, gradle test)
    if bin_name in {"mvn", "mvnw", "gradle", "gradlew"}:
        if any("test" in t.lower() for t in tokens[1:]):
            return True

    return False

def _is_walkthrough_step(step):
    if not isinstance(step, dict):
        return False
    source = step.get("source", "")
    step_type = step.get("type", "")

    # Check tool calls generating walkthrough.md
    raw_calls = step.get("tool_calls") or step.get("toolCall") or step.get("tool_call")
    if raw_calls:
        if isinstance(raw_calls, dict):
            raw_calls = [raw_calls]
        if isinstance(raw_calls, list):
            for tc in raw_calls:
                if isinstance(tc, dict):
                    args = tc.get("args") or {}
                    if isinstance(args, dict):
                        target = _extract_target_file(args)
                        if "walkthrough.md" in target.lower():
                            return True
                    elif isinstance(args, str) and "walkthrough.md" in args.lower():
                        return True

    # Check model response mentioning walkthrough.md
    if source == "MODEL" or step_type == "PLANNER_RESPONSE":
        content = str(step.get("content", ""))
        if "walkthrough.md" in content.lower():
            return True

    return False

def is_plan_execution_active(transcript_path, artifact_dir=None):
    if not transcript_path or not os.path.exists(transcript_path):
        return False
    try:
        last_approval_idx = -1
        last_walkthrough_idx = -1
        seen_implementation_plan = False
        has_plan_file = bool(artifact_dir and os.path.exists(os.path.join(artifact_dir, "implementation_plan.md")))

        parsed = parse_transcript(transcript_path)
        for idx, line, step in parsed.get("steps", []):
            source = step.get("source", "")
            step_type = step.get("type", "")
            content = str(step.get("content", ""))
            content_lower = content.lower()

            # Update seen_implementation_plan tracking linearly (no quadratic concatenation)
            if not seen_implementation_plan:
                if "implementation_plan" in content_lower or "implementation_plan" in line.lower():
                    seen_implementation_plan = True

            # Check for plan approval ONLY from user explicit input
            if source == "USER_EXPLICIT" and step_type == "USER_INPUT":
                # Strip system-injected metadata (e.g. <ADDITIONAL_METADATA> which contains /plan definition)
                clean_content = re.sub(r"<ADDITIONAL_METADATA>.*?</ADDITIONAL_METADATA>", "", content, flags=re.DOTALL)
                clean_content_lower = clean_content.lower()

                # An invocation of /plan is a planning command, never an approval to execute
                if "/plan" in clean_content_lower:
                    continue

                if "the user has approved this document" in clean_content_lower:
                    last_approval_idx = idx
                elif re.search(r"\bproceed\b", clean_content_lower):
                    if "implementation_plan" in clean_content_lower or seen_implementation_plan or has_plan_file:
                        last_approval_idx = idx

            # Deactivate plan mode when walkthrough.md is generated via tool calls or model response
            if last_approval_idx != -1 and idx > last_approval_idx:
                if _is_walkthrough_step(step):
                    last_walkthrough_idx = idx

        if last_approval_idx == -1:
            return False

        if last_walkthrough_idx > last_approval_idx:
            return False

        return True
    except Exception as exc:
        sys.stderr.write(f"Warning in is_plan_execution_active: {exc}\n")
        return False

def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout
    def emit(data):
        if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
            stdout.write(json.dumps({"decision": "allow"}) + "\n")
        else:
            stdout.write(json.dumps(data) + "\n")
    try:
        raw_payload = stdin.read()
        if not raw_payload or not raw_payload.strip():
            return emit({"decision": "deny", "reason": "Empty input payload"})
        data = json.loads(raw_payload)

        ledger = Ledger()

        def emit_deny(reason):
            try:
                turn_id, lines = get_turn_state(data.get("transcriptPath", ""))
                conv_id = data.get("conversationId", "unknown")
                step_idx = data.get("stepIdx", 0)
                ledger.insert_event(conv_id, str(turn_id), "PreToolUse", str(step_idx), "enforce", Event.PRIMARY_TOOL_DENIED.name, json.dumps({"reason": reason}))
            except Exception as exc:
                sys.stderr.write(f"Warning: {exc}\n")
            emit({"decision": "deny", "reason": reason})

        is_sub, may_delegate, remaining_depth, _, _ = is_subagent(data, ledger=ledger)
        tool_call = data.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        target_file = _extract_target_file(args)

        if tool_name in ["run_command", "default_api:run_command"]:
            cmd = args.get("CommandLine", "")
            destr_err = check_destructive_command(cmd)
            if destr_err:
                return emit_deny(destr_err)

        if tool_name in MUTATION_TOOLS:
            tamper_err = check_test_tampering(target_file, args)
            if tamper_err:
                return emit_deny(tamper_err)

        if not is_sub:
            if tool_name in ["manage_subagents", "default_api:manage_subagents"]:
                action = args.get("Action")
                now = time.time()
                if action == "kill":
                    conv_ids = args.get("ConversationIds") or []
                    for sub_id in conv_ids:
                        try:
                            with ledger._get_connection() as conn:
                                conn.execute(
                                    "UPDATE work_items SET status = 'TERMINATED', updated_at = ? "
                                    "WHERE status = 'ACTIVE' AND work_id IN (SELECT token_id FROM tokens WHERE claimed_by = ?)",
                                    (now, str(sub_id)),
                                )
                                conn.commit()
                        except Exception as exc:
                            sys.stderr.write(f"Warning in manage_subagents kill: {exc}\n")
                    return emit({"decision": "allow"})
                elif action == "kill_all":
                    parent_conv = data.get("conversationId", "")
                    try:
                        with ledger._get_connection() as conn:
                            conn.execute(
                                "UPDATE work_items SET status = 'TERMINATED', updated_at = ? "
                                "WHERE status = 'ACTIVE' AND parent_conv_id = ?",
                                (now, parent_conv),
                            )
                            conn.commit()
                    except Exception as exc:
                        sys.stderr.write(f"Warning in manage_subagents kill_all: {exc}\n")
                    return emit({"decision": "allow"})

            if tool_name in ["send_message", "default_api:send_message"]:
                raw_rec = args.get("Recipient") if args.get("Recipient") is not None else args.get("recipient")
                recipient = str(raw_rec or "").strip()
                if recipient.startswith('"') and recipient.endswith('"') and len(recipient) >= 2:
                    try:
                        decoded_rec = json.loads(recipient)
                        if isinstance(decoded_rec, str):
                            recipient = decoded_rec.strip()
                    except Exception as dec_err:
                        _ = dec_err
                        recipient = recipient[1:-1].strip()

                msg_val = args.get("Message") if args.get("Message") is not None else args.get("message")
                msg_str = str(msg_val or "").strip()
                if msg_str.startswith('"') and msg_str.endswith('"') and len(msg_str) >= 2:
                    try:
                        decoded_msg = json.loads(msg_str)
                        if isinstance(decoded_msg, str):
                            msg_str = decoded_msg.strip()
                        elif isinstance(decoded_msg, dict):
                            msg_str = json.dumps(decoded_msg)
                    except Exception as msg_err:
                        _ = msg_err

                is_valid_payload = False
                if recipient:
                    if os.environ.get("AGY_DISABLE_JSON_GATE") == "1":
                        is_valid_payload = True
                    else:
                        try:
                            parsed_msg = json.loads(msg_str) if isinstance(msg_str, str) else msg_str
                            if isinstance(parsed_msg, dict):
                                is_valid_payload = True
                        except (json.JSONDecodeError, ValueError) as json_err:
                            _ = json_err
                            is_valid_payload = False
                if is_valid_payload:
                    now = time.time()
                    turn_id, _ = get_turn_state(data.get("transcriptPath", ""))
                    conv_id = data.get("conversationId", "unknown")
                    step_idx = data.get("stepIdx", 0)
                    with ledger._get_connection() as conn:
                        row = conn.execute(
                            """
                            SELECT w.work_id
                            FROM work_items w
                            LEFT JOIN tokens t ON w.work_id = t.token_id
                            WHERE (t.claimed_by = ? OR t.token_id = ? OR w.work_id = ?)
                              AND w.parent_conv_id = ?
                              AND ? != ?
                            ORDER BY w.created_at DESC LIMIT 1
                            """,
                            (recipient, recipient, recipient, conv_id, recipient, conv_id)
                        ).fetchone()

                        if row and row[0]:
                            work_id = row[0]
                        elif os.environ.get("AGY_ALLOW_UNSEEDED_SEND_MESSAGE") == "1":
                            work_id = recipient
                            conn.execute(
                                "INSERT INTO tokens (token_id, claimed, claimed_by, created_at) VALUES (?, 1, ?, ?) "
                                "ON CONFLICT(token_id) DO UPDATE SET claimed = 1, claimed_by = excluded.claimed_by",
                                (recipient, recipient, now)
                            )
                        else:
                            # Recipient is not a known subagent of this conversation; allow plain send_message without tracking as handoff
                            return emit({"decision": "allow"})
                        conn.execute(
                            """
                            INSERT INTO work_items (work_id, status, created_at, updated_at, parent_conv_id, parent_turn_id, step_idx)
                            VALUES (?, 'ACTIVE', ?, ?, ?, ?, ?)
                            ON CONFLICT(work_id) DO UPDATE SET
                                status = 'ACTIVE',
                                updated_at = excluded.updated_at,
                                parent_conv_id = excluded.parent_conv_id,
                                parent_turn_id = excluded.parent_turn_id,
                                step_idx = excluded.step_idx
                            """,
                            (work_id, now, now, conv_id, str(turn_id), str(step_idx))
                        )
                        conn.commit()
                    ledger.insert_event(
                        conv_id, str(turn_id), "PreToolUse", str(step_idx), work_id, "WORK_PREPARED",
                        json.dumps({
                            "token": work_id,
                            "recipient": recipient,
                            "tool": "invoke",
                            "valid_handoff": True,
                            "parent_conv_id": conv_id,
                            "parent_turn_id": str(turn_id),
                        })
                    )
                    return emit({"decision": "allow"})

            transcript_path = data.get("transcriptPath", "")
            artifact_dir = data.get("artifactDirectoryPath") or data.get("artifact_dir")
            if not artifact_dir:
                conv_id = data.get("conversationId", "")
                base = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
                artifact_dir = os.path.join(base, "brain", conv_id) if conv_id else ""

            model = get_primary_model(data)
            if is_thinking_model(model):
                if tool_name in MUTATION_TOOLS:
                    if is_markdown_file(target_file) or is_artifact_path(target_file, artifact_dir):
                        return emit({"decision": "allow"})
                    return emit_deny(f"Attention Dilution Guard: Thinking Mode Restriction. Primary Agent ({model}) is restricted to thinking, planning, and markdown documentation. Non-markdown code modifications must be delegated to a flash subagent via invoke_subagent.")

                if tool_name in ["run_command", "default_api:run_command"]:
                    cmd = args.get("CommandLine", "")
                    if is_test_command(cmd) or is_build_command(cmd):
                        return emit_deny(f"Attention Dilution Guard: Thinking Mode Restriction. Primary Agent ({model}) is forbidden from running tests or build commands directly. Delegate execution to a flash subagent via invoke_subagent.")
                    return emit({"decision": "allow"})

                return emit({"decision": "allow"})

            if is_plan_execution_active(transcript_path, artifact_dir):
                if tool_name in MUTATION_TOOLS:
                    if is_markdown_file(target_file) or "docs/" in target_file.lower() or is_artifact_path(target_file, artifact_dir):
                        return emit({"decision": "allow"})
                    return emit_deny("Attention Dilution Guard: Primary Agent is forbidden from directly mutating workspace code during an active implementation plan. Delegate implementation to a subagent via invoke_subagent.")

                if tool_name in ["run_command", "default_api:run_command"]:
                    cmd = args.get("CommandLine", "")
                    if is_test_command(cmd):
                        return emit_deny("Attention Dilution Guard: Primary Agent is forbidden from running test suites directly during an active implementation plan. Delegate execution to a subagent via invoke_subagent.")

            return emit({"decision": "allow"})

        if is_sub:
            if tool_name in ["send_message", "default_api:send_message"]:
                parsed = parse_transcript(data.get("transcriptPath", ""))
                active_bg = parsed.get("active_bg_tasks") or []
                if active_bg:
                    bg_ids = ", ".join(active_bg)
                    return emit_deny(
                        f"Attention Guard: Cannot call send_message while background command task(s) are still running: {bg_ids}. "
                        f"Wait for each background task's <SYSTEM_MESSAGE> completion notification (by ending your turn) "
                        f"or explicitly terminate it via manage_task(Action=\"kill\", TaskId=\"...\") before reporting completion. "
                        f"Never fabricate <system_message> blocks."
                    )
            if tool_name in ["invoke_subagent", "manage_subagents", "default_api:invoke_subagent", "default_api:manage_subagents"]:
                if not may_delegate or remaining_depth <= 0:
                    return emit_deny("Attention Dilution Guard: Subagents are forbidden from delegating tasks further. Do not invoke or manage subagents.")
            if tool_name in ["run_command", "default_api:run_command"]:
                conv_id = data.get("conversationId", "unknown")
                turn_id, _ = get_turn_state(data.get("transcriptPath", ""))
                doom_err = check_subagent_doom_loop(ledger, conv_id, str(turn_id), tool_name, args)
                if doom_err:
                    return emit_deny(doom_err)
                return emit({"decision": "allow"})
            if tool_name in MUTATION_TOOLS:
                conv_id = data.get("conversationId", "unknown")
                record_subagent_file_edit(conv_id, target_file, ledger)
                return emit({"decision": "allow"})

        return emit({"decision": "allow"})
    except Exception as exc: emit({"decision": "deny", "reason": f"Attention Guard Exception in enforce-delegation: {exc}"})

if __name__ == "__main__": main()
