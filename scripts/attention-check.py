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

def check_walkthrough_requirement(payload, conv_id, min_mtime=None):
    artifact_dir = payload.get("artifactDirectoryPath", "")
    if not artifact_dir:
        base = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
        artifact_dir = os.path.join(base, "brain", conv_id)
    target = os.path.join(artifact_dir, "walkthrough.md")
    if not (os.path.isfile(target) and os.path.getsize(target) > 0):
        return False
    if min_mtime is not None:
        try:
            mtime = os.path.getmtime(target)
            if mtime < (min_mtime - 5.0):
                return False
        except OSError as exc:
            _ = exc
            return False
    return True

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
            conn.execute("UPDATE work_items SET status = 'TIMED_OUT' WHERE status NOT IN ('COMPLETED', 'TERMINATED', 'DONE', 'FAILED', 'TIMED_OUT') AND COALESCE(updated_at, created_at) < ?", (cutoff,))
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

            OK_REASONS = {"model_stop", "NO_TOOL_CALL", "TERMINAL_STEP_TYPE", "INJECTED_RESPONSE"}
            TIMEOUT_REASONS = {"max_steps_exceeded", "MAX_INVOCATIONS", "MAX_FORCED_INVOCATIONS", "MAX_TOKEN_BUDGET_EXCEEDED"}
            ERROR_REASONS = {"ERROR", "USER_CANCELED"}

            if not fully_idle:
                event_type = "WAITING"
                with ledger._get_connection() as conn:
                    conn.execute("UPDATE work_items SET updated_at = ? WHERE work_id = (SELECT token_id FROM tokens WHERE claimed_by = ?)", (time.time(), conv_id))
            elif error or term_reason in ERROR_REASONS:
                event_type = Event.WORK_TERMINATED_ERROR.name
            elif term_reason in TIMEOUT_REASONS:
                event_type = Event.WORK_TIMED_OUT.name
            elif fully_idle and term_reason in OK_REASONS and not error:
                event_type = Event.WORK_TERMINATED_OK.name

            if event_type and parent_conv_id and parent_turn_id is not None:
                if event_type in (Event.WORK_TERMINATED_OK.name, Event.WORK_TERMINATED_ERROR.name, Event.WORK_TIMED_OUT.name):
                    target_status = 'COMPLETED' if event_type == Event.WORK_TERMINATED_OK.name else ('FAILED' if event_type == Event.WORK_TERMINATED_ERROR.name else 'TIMED_OUT')
                    with ledger._get_connection() as conn:
                        cursor = conn.execute("UPDATE work_items SET status = ? WHERE status = 'ACTIVE' AND work_id = (SELECT token_id FROM tokens WHERE claimed_by = ?)", (target_status, conv_id))
                        if cursor.rowcount == 0:
                            return emit({"decision": "allow"})
                
                with ledger._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status NOT IN ('COMPLETED', 'TERMINATED', 'DONE', 'FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (parent_conv_id, str(parent_turn_id)))
                    all_work_terminal = (cursor.fetchone()[0] == 0)

                ledger.insert_event(parent_conv_id, str(parent_turn_id), "Stop", "0", conv_id, event_type, json.dumps({"child_id": conv_id, "all_work_terminal": all_work_terminal}))
            return emit({"decision": "allow"})

        tracker = os.path.join(get_cache_dir(), f"violation_{conv_id}_{turn_id}")
        current_state = get_current_fsm_state(ledger, conv_id, turn_id)

        if current_state in (State.OPEN, State.CLOSED):
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False}))
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
            reset_rejection_count(tracker)
            return emit({"decision": "allow"})

        if current_state == State.HANDOFF_PENDING:
            reset_rejection_count(tracker)
            return emit({"decision": "allow"})

        if current_state in (State.EXECUTION_ACTIVE, State.REVIEWING):
            with ledger._get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status NOT IN ('COMPLETED', 'TERMINATED', 'DONE', 'FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                active_count = cursor.fetchone()[0]
                cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                total_count = cursor.fetchone()[0]

            if total_count > 0 and active_count == 0:
                with ledger._get_connection() as conn:
                    cursor = conn.execute("SELECT COUNT(*) FROM work_items WHERE status IN ('FAILED', 'TIMED_OUT') AND parent_conv_id = ? AND parent_turn_id = ?", (conv_id, str(turn_id)))
                    failure_count = cursor.fetchone()[0]
                if failure_count == 0:
                    min_mtime = None
                    with ledger._get_connection() as conn:
                        cursor = conn.execute(
                            "SELECT MIN(created_at) FROM work_items WHERE parent_conv_id = ? AND parent_turn_id = ?",
                            (conv_id, str(turn_id))
                        )
                        row = cursor.fetchone()
                        if row and row[0] is not None:
                            try:
                                min_mtime = float(row[0])
                            except (ValueError, TypeError) as conv_err:
                                _ = conv_err
                    if not check_walkthrough_requirement(payload, conv_id, min_mtime=min_mtime):
                        rejection_count = increment_rejection_count(tracker)
                        if rejection_count >= MAX_STOP_REJECTIONS:
                            reset_rejection_count(tracker)
                            return emit({"decision": "allow"})
                        return emit({
                            "decision": "continue",
                            "reason": f"Attention Guard Walkthrough Gate: Subagents executed work, but walkthrough.md has not been generated or updated. Create or update walkthrough.md to document changes before completing the turn. (Retry {rejection_count}/{MAX_STOP_REJECTIONS})"
                        })
                    if current_state == State.EXECUTION_ACTIVE:
                        ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.WORK_TERMINATED_OK.name, json.dumps({"all_work_terminal": True}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
                    reset_rejection_count(tracker)
                    return emit({"decision": "allow"})
                else:
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.WORK_TIMED_OUT.name, json.dumps({"reason": "Orphaned work timed out"}))
                    current_state = State.RECOVERY_REQUIRED
            elif active_count > 0:
                # Primary agent has active subagent work running in background.
                # Allow turn to finish so Primary agent can wait for asynchronous subagent response.
                reset_rejection_count(tracker)
                return emit({"decision": "allow"})
            else:
                if current_state == State.REVIEWING:
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False}))
                    ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
                reset_rejection_count(tracker)
                return emit({"decision": "allow"})

        if current_state == State.RECOVERY_REQUIRED:
            reset_rejection_count(tracker)
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.STOP_REQUESTED.name, json.dumps({"active_work": False, "recovery_handled": True}))
            ledger.insert_event(conv_id, str(turn_id), "Stop", "0", "self", Event.TURN_CLOSED.name, json.dumps({}))
            return emit({"decision": "allow"})
    except Exception as exc:
        sys.stderr.write(f"Warning: {exc}\n")
    emit({"decision": "allow"})

if __name__ == "__main__": main()
