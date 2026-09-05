#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
import json
import time
from common import is_subagent, get_cache_dir, get_turn_state
from ledger import Ledger
from fsm import FSM, Event, State

MAX_STOP_REJECTIONS = 2

def get_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    if os.path.exists(count_file):
        try:
            with open(count_file, "r") as f:
                return int(f.read().strip())
        except Exception:
            pass
    return 0

def increment_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    count = get_rejection_count(tracker) + 1
    with open(count_file, "w") as f:
        f.write(str(count))
    return count

def reset_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    if os.path.exists(count_file):
        try:
            os.remove(count_file)
        except: pass

def get_current_fsm_state(ledger, conv_id, turn_id):
    fsm = FSM()
    with ledger._get_connection() as conn:
        cursor = conn.execute("SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at ASC", (f"{conv_id}_{turn_id}_%",))
        for row in cursor:
            event_type_str = row[0]
            payload = json.loads(row[1]) if row[1] else {}
            
            try:
                event = Event[event_type_str]
                fsm.transition(event, payload)
            except KeyError:
                pass
    return fsm.state

def main(argv=None, stdin=None, stdout=None):
    if argv is None:
        argv = sys.argv
    if stdin is None:
        stdin = sys.stdin
    if stdout is None:
        stdout = sys.stdout

    def emit(data):
        stdout.write(json.dumps(data) + "\n")

    try:
        payload = json.loads(stdin.read())
    except Exception:
        emit({"decision": "allow"})
        return

    is_sub, _, _, parent_conv_id, parent_turn_id = is_subagent(payload)
    ledger = Ledger()
    conv_id = payload.get("conversationId", "unknown")
    turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))

    if is_sub:
        fully_idle = payload.get("fullyIdle", True)
        term_reason = payload.get("terminationReason", "model_stop")
        error = payload.get("error", None)
        
        event_type = None
        if not fully_idle:
            event_type = "WAITING"
        elif error:
            event_type = Event.WORK_TERMINATED_ERROR.name
        elif term_reason == "max_steps_exceeded":
            event_type = Event.WORK_TIMED_OUT.name
        elif fully_idle and term_reason == "model_stop" and not error:
            event_type = Event.WORK_TERMINATED_OK.name
            
        if event_type and parent_conv_id and parent_turn_id:
            # We record to the parent's ledger so parent FSM can see it
            ledger.insert_event(parent_conv_id, str(parent_turn_id), "Stop", "0", conv_id, event_type, json.dumps({"child_id": conv_id}))
            
        emit({"decision": "allow"})
        return

    tracker = os.path.join(get_cache_dir(), f"violation_{conv_id}_{turn_id}")
    
    current_state = get_current_fsm_state(ledger, conv_id, turn_id)
    
    if current_state in (State.OPEN, State.REVIEWING, State.CLOSED):
        reset_rejection_count(tracker)
        emit({"decision": "allow"})
        return
        
    if current_state == State.HANDOFF_PENDING:
        reset_rejection_count(tracker)
        emit({"decision": "allow"})
        return
        
    if current_state == State.EXECUTION_ACTIVE:
        if payload.get("fullyIdle", True):
            # Inconsistent state, recover
            current_state = State.RECOVERY_REQUIRED
        else:
            reset_rejection_count(tracker)
            emit({"decision": "allow"})
            return

    if current_state == State.RECOVERY_REQUIRED:
        rejection_count = get_rejection_count(tracker)
        if rejection_count >= MAX_STOP_REJECTIONS:
            reset_rejection_count(tracker)
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"retries_exhausted": True}))
            emit({"decision": "allow"})
            return

        rejection_count = increment_rejection_count(tracker)
        injected_text = f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"
        
        emit({"decision": "continue", "reason": injected_text})
        return

    emit({"decision": "allow"})

if __name__ == "__main__":
    main()
