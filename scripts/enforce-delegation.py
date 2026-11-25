#!/usr/bin/env python3
import json
import os
import re
import shlex
import sys
import time
import uuid
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
from common import (
    extract_active_bg_tasks,
    is_subagent,
    scan_transcript_header,
    validate_no_raw_log_dump,
)
from kubectl_guard import check_kubectl_mutation

MUTATION_TOOLS = {
    "write_to_file",
    "default_api:write_to_file",
    "replace_file_content",
    "default_api:replace_file_content",
    "multi_replace_file_content",
    "default_api:multi_replace_file_content",
    "write_file",
    "default_api:write_file",
    "edit_file",
    "default_api:edit_file",
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
    if base.endswith(
        (
            ".test.ts",
            ".spec.ts",
            ".test.tsx",
            ".spec.tsx",
            ".test.js",
            ".spec.js",
            ".test.jsx",
            ".spec.jsx",
            ".test.mjs",
            ".spec.mjs",
            ".test.cjs",
            ".spec.cjs",
            "_test.go",
        )
    ):
        return True
    return False


def is_test_command(cmd_str) -> bool:
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
            bin_name = bin_name[: -len(ext)]
            break

    if bin_name in {"pytest", "vitest", "jest", "mocha", "ctest", "ava"}:
        return True

    if bin_name in {"python", "python3"}:
        i = 1
        while i < len(tokens):
            arg = tokens[i]
            if arg == "-m":
                if i + 1 < len(tokens):
                    mod = tokens[i + 1].lower()
                    return mod in {"pytest", "unittest"} or mod.startswith(("pytest.", "unittest."))
                return False
            if arg.startswith("-m"):
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
            script_base = os.path.basename(arg).lower()
            return script_base in {"pytest", "pytest.py", "unittest", "unittest.py"}
        return False

    if bin_name in {"cargo", "go", "npm", "pnpm", "yarn", "bun", "dotnet"}:
        if any(t == "test" for t in tokens[1:]):
            return True

    if bin_name in {"mvn", "mvnw", "gradle", "gradlew"}:
        if any("test" in t.lower() for t in tokens[1:]):
            return True

    return False


def _strip_quotes_and_comments(line: str, lang_ext: str) -> str:
    if lang_ext == "ts":
        line = re.sub(r"`(?:\\.|[^`\\])*`", '""', line)
    line = re.sub(r'"(?:\\.|[^"\\])*"', '""', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "''", line)

    if lang_ext == "py":
        line = re.sub(r"#.*$", "", line)
    elif lang_ext in ("ts", "go"):
        line = re.sub(r"//.*$", "", line)
        line = re.sub(r"/\*.*?\*/", "", line)

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
        clean_replacement = re.sub(r"`[\s\S]*?`", '""', clean_replacement)
        clean_replacement = re.sub(r"/\*[\s\S]*?\*/", "", clean_replacement)

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
                    if t.startswith("-") and t != "--":
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
                has_force = any(
                    t in ("--force", "-f") or (t.startswith("-") and not t.startswith("--") and "f" in t)
                    for t in tokens[2:]
                )
                if has_force and not has_lease:
                    return f"Attention Guard: Destructive command '{cmd_str}' is forbidden (git push --force without --force-with-lease)."

        if bin_name == "rm":
            is_recursive = False
            targets = []
            for t in tokens[1:]:
                if t.startswith("-") and t != "--":
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
                        if tgt == "" and any(q in s for q in ('""', "''")):
                            return f"Attention Guard: Sweeping destructive command '{cmd_str}' is forbidden (catastrophic rm targeting '{tgt}')."
    return check_kubectl_mutation(cmd_str)


def record_subagent_file_edit(conv_id: str, target_file: str = "", ledger=None):
    if ledger is None:
        from ledger import Ledger
        ledger = Ledger()
    now = time.time()
    event_id = f"{conv_id}_subagent_file_edit_{now}_{uuid.uuid4().hex[:8]}"
    try:
        with ledger._get_connection() as conn:
            conn.execute(
                "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                (event_id, "SUBAGENT_FILE_EDIT", json.dumps({"target_file": target_file}), now),
            )
    except Exception as exc:
        sys.stderr.write(f"Warning in record_subagent_file_edit: {exc}\n")


def normalize_command_signature(cmd: str) -> str:
    if not cmd or not isinstance(cmd, str):
        return ""
    c = cmd.strip()
    while True:
        prev = c
        c = re.sub(r"^(?:rtk\s+proxy\s+|rtk\s+|sudo\s+)", "", c).strip()
        if c == prev:
            break

    c = re.sub(r"^(?:rtk\s+)?sleep\s+\d+\s*&&\s*", "", c).strip()

    while True:
        prev = c
        c = re.sub(r"^(?:rtk\s+proxy\s+|rtk\s+|sudo\s+)", "", c).strip()
        if c == prev:
            break

    if c.startswith("pgrep") or re.search(r"\bpgrep\b", c):
        m_pid = re.search(r"-[pP]\s*(\d+)", c)
        if m_pid:
            return f"POLL_PROC:{m_pid.group(1)}"
        m_target = re.search(r"\bpgrep\b(?:\s+-[a-zA-Z0-9]+)*\s+([^\s|&;]+)", c)
        if m_target:
            target = m_target.group(1).strip()
            if target:
                return f"POLL_PROC:{target}"

    if c.startswith("ps ") or c == "ps" or re.search(r"\bps\b", c):
        m_grep = re.search(r"\|\s*(?:rtk\s+)?grep\b(?:\s+-[a-zA-Z0-9]+)*\s+['\"]?([^'\"\s|&;]+)", c)
        if m_grep:
            grep_target = m_grep.group(1).strip()
            if grep_target:
                return f"POLL_PROC:{grep_target}"
        m_pid = re.search(r"-[pP]\s*(\d+)", c)
        if m_pid:
            return f"POLL_PROC:{m_pid.group(1)}"

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

    if re.search(r"\bpython[0-9.]*\s+-c\b", c):
        is_write = any(w in c for w in ('"w"', "'w'", '"a"', "'a'", '"w+"', "'w+'", "write_text", "write_bytes"))
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

    if args and hasattr(args[0], "_get_connection"):
        ledger = args[0]
        if len(args) > 1:
            conv_id = str(args[1])
        if len(args) > 2:
            turn_id = str(args[2])
        if len(args) > 3:
            tool_name = str(args[3])
        if len(args) > 4:
            tool_args = args[4]
    elif args and isinstance(args[0], str):
        conv_id = args[0]
        if len(args) > 1:
            if isinstance(args[1], dict):
                tool_args = args[1]
            else:
                tool_args = {"CommandLine": str(args[1])}
        if len(args) > 2 and isinstance(args[2], int):
            threshold = args[2]
        ledger = kwargs.get("ledger") or (args[3] if len(args) > 3 and hasattr(args[3], "_get_connection") else None)

    if ledger is None:
        from ledger import Ledger
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
                "SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at DESC, rowid DESC",
                (f"{conv_id}_%",),
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
            ledger.insert_event(
                conv_id,
                str(turn_id),
                "PreToolUse",
                uuid.uuid4().hex[:8],
                "doom_loop",
                "BREAKER_STATE_CHANGE",
                json.dumps({"state": "OPEN", "signature": cmd_sig, "count": identical_count + 1}),
            )
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
                (event_id, "SUBAGENT_COMMAND", json.dumps({"command": cmd_norm}), now),
            )
    except Exception as exc:
        sys.stderr.write(f"Warning in check_subagent_doom_loop: {exc}\n")

    return None


def main(argv=None, stdin=None, stdout=None):
    if argv is None:
        argv = sys.argv
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    def emit(data):
        if os.environ.get("AGY_ATTENTION_GUARD_OBSERVATION_MODE") == "1":
            stdout.write(json.dumps({"decision": "allow"}) + "\n")
        else:
            stdout.write(json.dumps(data) + "\n")

    try:
        if os.environ.get("AGY_ATTENTION_GUARD_KILL_SWITCH") == "1":
            return emit({"decision": "allow"})

        raw_payload = stdin.read()
        if not raw_payload or not raw_payload.strip():
            return emit({"decision": "deny", "reason": "Empty input payload"})
        data = json.loads(raw_payload)

        _ledger_instance = None

        def get_ledger():
            nonlocal _ledger_instance
            if _ledger_instance is None:
                from ledger import Ledger
                _ledger_instance = Ledger()
            return _ledger_instance

        is_sub, may_delegate, remaining_depth, _, _ = is_subagent(data)
        tool_call = data.get("toolCall", {})
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})
        target_file = _extract_target_file(args)

        def emit_deny(reason: str):
            try:
                turn_id = scan_transcript_header(data.get("transcriptPath", "")).get("turn_id", 0)
                conv_id = data.get("conversationId", "unknown")
                step_idx = data.get("stepIdx", 0)
                get_ledger().insert_event(
                    conv_id,
                    str(turn_id),
                    "PreToolUse",
                    f"{step_idx}_{uuid.uuid4().hex[:8]}",
                    "enforce",
                    "PRIMARY_TOOL_DENIED",
                    json.dumps({"tool": tool_name, "is_sub": bool(is_sub), "reason": reason}),
                )
            except Exception as exc:
                sys.stderr.write(f"Warning: {exc}\n")
            emit({"decision": "deny", "reason": reason})

        if tool_name in ("run_command", "default_api:run_command"):
            cmd = args.get("CommandLine", "") if isinstance(args, dict) else ""
            destr_err = check_destructive_command(cmd)
            if destr_err:
                return emit_deny(destr_err)

        if tool_name in MUTATION_TOOLS:
            tamper_err = check_test_tampering(target_file, args)
            if tamper_err:
                return emit_deny(tamper_err)

        if not is_sub:
            return emit({"decision": "allow"})

        if tool_name in ("send_message", "default_api:send_message"):
            active_bg = extract_active_bg_tasks(data.get("transcriptPath", ""))
            if active_bg:
                bg_ids = ", ".join(active_bg)
                return emit_deny(
                    f"Attention Guard: Cannot call send_message while background command task(s) are still running: {bg_ids}. "
                    f"Wait for each background task's <SYSTEM_MESSAGE> completion notification (by ending your turn) "
                    f"or explicitly terminate it via manage_task(Action=\"kill\", TaskId=\"...\") before reporting completion. "
                    f"Never fabricate <system_message> blocks."
                )
            raw_msg = args.get("Message") if args.get("Message") is not None else args.get("message")
            msg_text = json.dumps(raw_msg) if isinstance(raw_msg, dict) else str(raw_msg or "")
            ok_raw, raw_err = validate_no_raw_log_dump(msg_text)
            if not ok_raw:
                return emit_deny(raw_err or "Attention Guard: Raw log dump detected in send_message.")
            return emit({"decision": "allow"})

        if tool_name in ("run_workflow", "default_api:run_workflow", "swarm", "default_api:swarm"):
            return emit_deny("Attention Dilution Guard: Subagents are forbidden from invoking run_workflow or swarm.")

        if tool_name in (
            "invoke_subagent",
            "manage_subagents",
            "default_api:invoke_subagent",
            "default_api:manage_subagents",
        ):
            if not may_delegate or remaining_depth <= 0:
                return emit_deny(
                    "Attention Dilution Guard: Subagents are forbidden from delegating tasks further. Do not invoke or manage subagents."
                )
            return emit({"decision": "allow"})

        if tool_name in ("run_command", "default_api:run_command"):
            conv_id = data.get("conversationId", "unknown")
            turn_id = scan_transcript_header(data.get("transcriptPath", "")).get("turn_id", 0)
            doom_err = check_subagent_doom_loop(get_ledger(), conv_id, str(turn_id), tool_name, args)
            if doom_err:
                return emit_deny(doom_err)
            return emit({"decision": "allow"})

        if tool_name in MUTATION_TOOLS:
            conv_id = data.get("conversationId", "unknown")
            record_subagent_file_edit(conv_id, target_file, get_ledger())
            return emit({"decision": "allow"})

        return emit({"decision": "allow"})
    except Exception as exc:
        emit({"decision": "deny", "reason": f"Attention Guard Exception in enforce-delegation: {exc}"})


if __name__ == "__main__":
    main()
