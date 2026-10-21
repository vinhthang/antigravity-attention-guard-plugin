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
    if base.endswith(".test.ts") or base.endswith(".spec.ts") or base.endswith("_test.go"):
        return True
    return False

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
                target += " " + str(chunk.get("Target") or chunk.get("TargetContent") or "")
                replacement += " " + str(chunk.get("Replacement") or chunk.get("ReplacementContent") or "")

    for pattern in TEST_TAMPER_PATTERNS:
        if pattern in replacement and pattern not in target:
            return (
                f"Attention Guard: Test tampering detected. Introducing test-skipping marker or bypass "
                f"'{pattern}' in test file '{target_file}' is forbidden."
            )
    return None

def check_destructive_command(cmd_str: str) -> Optional[str]:
    if not cmd_str or not isinstance(cmd_str, str):
        return None
    sub_cmds = re.split(r"[;&|]+", cmd_str)
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
                    if norm in catastrophic or tgt in catastrophic or norm == "":
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
                if recorded_cmd.strip() == cmd_norm:
                    identical_count += 1
                else:
                    break

        if identical_count >= (threshold - 1):
            return (
                f"Attention Guard: Subagent doom-loop circuit breaker. "
                f"Command '{cmd_norm}' executed {identical_count + 1} times consecutively without intervening file edits."
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

        with open(transcript_path, "r", encoding="utf-8") as f:
            for idx, raw_line in enumerate(f):
                line = raw_line.strip()
                if not line:
                    continue

                try:
                    step = json.loads(line)
                except Exception:
                    step = {}

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

        def emit_deny(reason):
            try:
                turn_id, lines = get_turn_state(data.get("transcriptPath", ""))
                conv_id = data.get("conversationId", "unknown")
                step_idx = data.get("stepIdx", 0)
                Ledger().insert_event(conv_id, str(turn_id), "PreToolUse", str(step_idx), "enforce", Event.PRIMARY_TOOL_DENIED.name, json.dumps({"reason": reason}))
            except Exception as exc:
                sys.stderr.write(f"Warning: {exc}\n")
            emit({"decision": "deny", "reason": reason})

        is_sub, may_delegate, remaining_depth, _, _ = is_subagent(data)
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
            if tool_name in ["invoke_subagent", "manage_subagents", "default_api:invoke_subagent", "default_api:manage_subagents"]:
                if not may_delegate or remaining_depth <= 0:
                    return emit_deny("Attention Dilution Guard: Subagents are forbidden from delegating tasks further. Do not invoke or manage subagents.")
            if tool_name in ["run_command", "default_api:run_command"]:
                conv_id = data.get("conversationId", "unknown")
                turn_id, _ = get_turn_state(data.get("transcriptPath", ""))
                doom_err = check_subagent_doom_loop(Ledger(), conv_id, str(turn_id), tool_name, args)
                if doom_err:
                    return emit_deny(doom_err)
                return emit({"decision": "allow"})
            if tool_name in MUTATION_TOOLS:
                conv_id = data.get("conversationId", "unknown")
                record_subagent_file_edit(conv_id, target_file, Ledger())
                return emit({"decision": "allow"})

        return emit({"decision": "allow"})
    except Exception as exc: emit({"decision": "deny", "reason": f"Attention Guard Exception in enforce-delegation: {exc}"})

if __name__ == "__main__": main()
