#!/usr/bin/env python3
import sys, os, json, time
sys.path.insert(0, os.path.dirname(__file__))
from common import is_subagent, get_cache_dir, get_turn_state
from ledger import Ledger
from fsm import FSM, Event, State

MAX_STOP_REJECTIONS = 2
def get_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    if os.path.exists(count_file):
        try: return int(open(count_file, "r").read().strip())
        except Exception as exc: sys.stderr.write(f"Warning: {exc}\n")
    return 0
def increment_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    count = get_rejection_count(tracker) + 1
    open(count_file, "w").write(str(count))
    return count
def reset_rejection_count(tracker):
    count_file = tracker + "_stop_count"
    try: os.remove(count_file)
    except Exception as exc: sys.stderr.write(f"Warning: {exc}\n")

def check_walkthrough_requirement(payload, conv_id):
    artifact_dir = payload.get("artifactDirectoryPath", "")
    if not artifact_dir:
        base = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
        artifact_dir = os.path.join(base, "brain", conv_id)
    target = os.path.join(artifact_dir, "walkthrough.md")
    return os.path.isfile(target) and os.path.getsize(target) > 0

def get_current_fsm_state(ledger, conv_id, turn_id):
    fsm = FSM()
    with ledger._get_connection() as conn:
        for row in conn.execute("SELECT type, payload FROM events WHERE event_id LIKE ? ORDER BY created_at ASC", (f"{conv_id}_{turn_id}_%",)):
            try: fsm.transition(Event[row[0]], json.loads(row[1]) if row[1] else {})
            except KeyError as exc: sys.stderr.write(f"Warning: {exc}\n")
    return fsm.state

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
        if os.environ.get("AGY_ATTENTION_GUARD_KILL_SWITCH") == "1":
            return emit({"decision": "allow"})
        payload = json.loads(stdin.read())
    except Exception: return emit({"decision": "allow"})
    try: ledger = Ledger()
    except Exception: return emit({"decision": "allow"})

    try:
        with ledger._get_connection() as conn:
            cutoff = time.time() - 86400
            conn.execute("UPDATE work_items SET status = 'TIMED_OUT' WHERE status NOT IN ('TERMINATED', 'FAILED', 'TIMED_OUT') AND COALESCE(updated_at, created_at) < ?", (cutoff,))
    except Exception as exc:
        sys.stderr.write(f"Warning: {exc}\n")

    try:
        is_sub, _, _, parent_conv_id, parent_turn_id = is_subagent(payload)
        conv_id = payload.get("conversationId", "unknown")
        turn_id, _ = get_turn_state(payload.get("transcriptPath", ""))

        if is_sub:
            fully_idle = payload.get("fullyIdle", True)
            term_reason = payload.get("terminationReason", "model_stop")
            error = payload.get("error", None)
            event_type = None

            if not fully_idle:
                event_type = "WAITING"
                with ledger._get_connection() as conn:
                    conn.execute("UPDATE work_items SET updated_at = ? WHERE work_id = (SELECT token_id FROM tokens WHERE claimed_by = ?)", (time.time(), conv_id))
            elif error: event_type = Event.WORK_TERMINATED_ERROR.name
            elif term_reason == "max_steps_exceeded": event_type = Event.WORK_TIMED_OUT.name
            elif fully_idle and term_reason == "model_stop" and not error: event_type = Event.WORK_TERMINATED_OK.name

            if event_type and parent_conv_id and parent_turn_id is not None:
                if event_type in (Event.WORK_TERMINATED_OK.name, Event.WORK_TERMINATED_ERROR.name, Event.WORK_TIMED_OUT.name):
                    with ledger._get_connection() as conn:
                        cursor = conn.execute("UPDATE work_items SET status = 'TERMINATED' WHERE status = 'ACTIVE' AND work_id = (SELECT token_id FROM tokens WHERE claimed_by = ?)", (conv_id,))
                        if cursor.rowcount == 0:
                            return emit({"decision": "allow"})
                
                with ledger._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status NOT IN ('TERMINATED', 'FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (parent_conv_id, str(parent_turn_id)))
                    all_work_terminal = (cursor.fetchone()[0] == 0)

                ledger.insert_event(parent_conv_id, str(parent_turn_id), "Stop", "0", conv_id, event_type, json.dumps({"child_id": conv_id, "all_work_terminal": all_work_terminal}))
            return emit({"decision": "allow"})

        tracker = os.path.join(get_cache_dir(), f"violation_{conv_id}_{turn_id}")
        current_state = get_current_fsm_state(ledger, conv_id, turn_id)

        if current_state in (State.OPEN, State.REVIEWING, State.CLOSED):
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False}))
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
            reset_rejection_count(tracker)
            return emit({"decision": "allow"})

        if current_state == State.HANDOFF_PENDING:
            reset_rejection_count(tracker)
            return emit({"decision": "allow"})

        if current_state == State.EXECUTION_ACTIVE:
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status NOT IN ('TERMINATED', 'FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                active_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                total_count = cursor.fetchone()[0]

            if total_count > 0 and active_count == 0:
                with ledger._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status IN ('FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                    failure_count = cursor.fetchone()[0]
                if failure_count == 0:
                    if not check_walkthrough_requirement(payload, conv_id):
                        rejection_count = increment_rejection_count(tracker)
                        if rejection_count >= MAX_STOP_REJECTIONS:
                            reset_rejection_count(tracker)
                            return emit({"decision": "allow"})
                        return emit({
                            "decision": "continue",
                            "reason": f"Attention Guard Walkthrough Gate: Subagents executed work, but walkthrough.md has not been generated or updated. Create or update walkthrough.md to document changes before completing the turn. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"
                        })
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.WORK_TERMINATED_OK.name, json.dumps({"all_work_terminal": True}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
                    reset_rejection_count(tracker)
                    return emit({"decision": "allow"})
                else:
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.WORK_TIMED_OUT.name, json.dumps({"reason": "Orphaned work timed out"}))
                    current_state = State.RECOVERY_REQUIRED
            elif active_count > 0 and payload.get("fullyIdle", True):
                ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.WORK_TERMINATED_ERROR.name, json.dumps({"reason": "Primary idled while active"}))
                current_state = State.RECOVERY_REQUIRED
            else:
                reset_rejection_count(tracker)
                return emit({"decision": "allow"})

        if current_state == State.RECOVERY_REQUIRED:
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status NOT IN ('TERMINATED', 'FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                active_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                total_count = cursor.fetchone()[0]

            if total_count > 0 and active_count == 0:
                with ledger._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status IN ('FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                    failure_count = cursor.fetchone()[0]
                if failure_count == 0:
                    if not check_walkthrough_requirement(payload, conv_id):
                        rejection_count = increment_rejection_count(tracker)
                        if rejection_count >= MAX_STOP_REJECTIONS:
                            reset_rejection_count(tracker)
                            return emit({"decision": "allow"})
                        return emit({
                            "decision": "continue",
                            "reason": f"Attention Guard Walkthrough Gate: Subagents executed work, but walkthrough.md has not been generated or updated. Create or update walkthrough.md to document changes before completing the turn. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"
                        })
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False, "auto_recovered": True}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
                    reset_rejection_count(tracker)
                    return emit({"decision": "allow"})

            rejection_count = get_rejection_count(tracker)
            if rejection_count >= MAX_STOP_REJECTIONS:
                reset_rejection_count(tracker)
                ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"retries_exhausted": True}))
                return emit({"decision": "allow"})
            rejection_count = increment_rejection_count(tracker)
            return emit({"decision": "continue", "reason": f"Attention Guard Refresh: Remember you are the Primary Agent. Delegate all execution to subagents. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"})
    except Exception as exc:
        sys.stderr.write(f"Warning: {exc}\n")
    emit({"decision": "allow"})

if __name__ == "__main__": main()
