#!/usr/bin/env python3
import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))
from ledger import Ledger
from fsm import Event

def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout
    def emit(data): stdout.write(json.dumps(data) + "\n")
    try:
        input_data = stdin.read()
        if not input_data: return emit({})
        payload = json.loads(input_data)
        ledger = Ledger()
        session_id = payload.get("sessionId") or payload.get("session_id") or payload.get("conversationId") or "default"

        tool_input = payload.get("tool_input_str") or payload.get("toolInput") or payload.get("toolCall") or payload.get("tool_call") or payload.get("args") or payload.get("input") or ""
        tool_input_str = json.dumps(tool_input) if not isinstance(tool_input, str) else tool_input

        tool_output = payload.get("tool_output_str") or payload.get("toolOutput") or payload.get("toolResult") or payload.get("result") or payload.get("output") or payload.get("error") or ""
        tool_output_str = json.dumps(tool_output) if not isinstance(tool_output, str) else tool_output

        ledger.record_tool_chars(str(session_id), len(tool_input_str) + len(tool_output_str))

        actor_id = payload.get("conversationId", "unknown")
        from common import get_turn_state
        turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))
        step_idx = payload.get("stepIdx", 0)
        error = payload.get("error")
        if error:
            event_type = Event.HANDOFF_FAILED.name
            with ledger._get_connection() as conn:
                conn.execute("UPDATE work_items SET status = 'FAILED' WHERE parent_conv_id = ? AND parent_turn_id = ? AND step_idx = ? AND status = 'ACTIVE'", (actor_id, str(turn_id), str(step_idx)))
        else:
            event_type = Event.HANDOFF_ACCEPTED.name
        ledger.insert_event(actor_id, str(turn_id), "PostToolUse", str(step_idx), "invoke", event_type, json.dumps({"error": error}))
        emit({})
    except Exception:
        emit({})

if __name__ == "__main__": main()
