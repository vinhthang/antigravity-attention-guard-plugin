#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json

from ledger import Ledger
from fsm import Event

def main(argv=None, stdin=None, stdout=None):
    if argv is None: argv = sys.argv
    if stdin is None: stdin = sys.stdin
    if stdout is None: stdout = sys.stdout

    def emit(data):
        stdout.write(json.dumps(data) + "\n")

    try:
        input_data = stdin.read()
        if not input_data:
            emit({})
            return
            
        payload = json.loads(input_data)
        
        ledger = Ledger()
        actor_id = payload.get("conversationId", "unknown")
        
        from common import get_turn_state
        turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))
        
        step_idx = payload.get("stepIndex", 0)
        error = payload.get("error")
        
        event_type = Event.HANDOFF_FAILED.name if error else Event.HANDOFF_ACCEPTED.name
        ledger.insert_event(actor_id, str(turn_id), "PostToolUse", str(step_idx), "invoke", event_type, json.dumps({"error": error}))
        
        emit({})
    except Exception:
        emit({})

if __name__ == "__main__":
    main()
