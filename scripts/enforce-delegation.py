#!/usr/bin/env python3
import sys, os, json, shlex, re
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
                        target = str(args.get("TargetFile") or args.get("target_file") or args.get("path") or args.get("file_path") or "")
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

        if not is_sub:
            transcript_path = data.get("transcriptPath", "")
            artifact_dir = data.get("artifactDirectoryPath") or data.get("artifact_dir")
            if not artifact_dir:
                conv_id = data.get("conversationId", "")
                base = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
                artifact_dir = os.path.join(base, "brain", conv_id) if conv_id else ""

            model = get_primary_model(data)
            if is_thinking_model(model):
                if tool_name in ["write_to_file", "default_api:write_to_file", "replace_file_content", "default_api:replace_file_content"]:
                    target_file = args.get("TargetFile") or args.get("target_file") or args.get("path") or ""
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
                if tool_name in ["write_to_file", "default_api:write_to_file"]:
                    target_file = args.get("TargetFile") or args.get("target_file") or args.get("path") or ""
                    if is_markdown_file(target_file) or "docs/" in target_file.lower() or is_artifact_path(target_file, artifact_dir):
                        return emit({"decision": "allow"})
                    return emit_deny("Attention Dilution Guard: Primary Agent is forbidden from directly mutating workspace code during an active implementation plan. Delegate implementation to a subagent via invoke_subagent.")

                if tool_name in ["replace_file_content", "default_api:replace_file_content"]:
                    target_file = args.get("TargetFile") or args.get("target_file") or args.get("path") or ""
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
                return emit({"decision": "allow"})

        return emit({"decision": "allow"})
    except Exception as exc: emit({"decision": "deny", "reason": f"Attention Guard Exception in enforce-delegation: {exc}"})

if __name__ == "__main__": main()
