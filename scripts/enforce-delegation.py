#!/usr/bin/env python3
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent, get_cache_dir, get_turn_state
from ledger import Ledger
from fsm import Event
from command_validator import validate_command

def is_artifact_path(target_file, artifact_dir):
    if not target_file: return False
    norm_target = os.path.realpath(os.path.abspath(target_file))
    if artifact_dir:
        norm_artifact = os.path.realpath(os.path.abspath(artifact_dir))
        if os.path.commonpath([norm_target, norm_artifact]) == norm_artifact: return True
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
            return emit({"decision": "allow"})

        if is_sub:
            if tool_name in ["invoke_subagent", "manage_subagents", "default_api:invoke_subagent", "default_api:manage_subagents"]:
                if not may_delegate or remaining_depth <= 0:
                    return emit_deny("Attention Dilution Guard: Subagents are forbidden from delegating tasks further. Do not invoke or manage subagents.")
            if tool_name in ["run_command", "default_api:run_command"]:
                cmd = args.get("CommandLine", "")
                cwd = args.get("Cwd", "") or os.getcwd()
                valid, err = validate_command(cmd, workspace_root=cwd)
                if not valid:
                    return emit_deny(f"Attention Guard Command Policy Violation: {err}")
            return emit({"decision": "allow"})

        return emit({"decision": "allow"})
    except Exception as exc: emit({"decision": "deny", "reason": f"Attention Guard Exception in enforce-delegation: {exc}"})

if __name__ == "__main__": main()
