#!/usr/bin/env python3
import sys, os, json, sqlite3
sys.path.insert(0, os.path.dirname(__file__))
from fsm import FSM, Event

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnostics.py <conversation_id>")
        sys.exit(1)
    conv_id = sys.argv[1]
    base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
    db_path = os.path.join(base_dir, "attention_guard.db")
    if not os.path.exists(db_path):
        print("No database found.")
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        return
    
    print(f"Diagnostics for Conversation ID: {conv_id}\n" + "-" * 50)
    try:
        events = conn.execute("SELECT event_id, type, payload, created_at FROM events WHERE event_id LIKE ? ORDER BY created_at ASC", (f"{conv_id}_%",)).fetchall()
    except sqlite3.Error as e:
        print(f"Database query error: {e}")
        return
        
    if not events: return print("No events found.")
    fsm = FSM()
    workers = set()
    max_depth = 0
    decisions = 0
    denied = 0
    for row in events:
        event_id, ev_type, payload_str, created_at = row
        payload = json.loads(payload_str) if payload_str else {}
        try: fsm.transition(Event[ev_type], payload)
        except KeyError: pass
        if ev_type == "WORK_PREPARED":
            workers.add(payload.get("token"))
            max_depth = max(max_depth, payload.get("remaining_depth", 0))
        if ev_type == "PRIMARY_TOOL_DENIED": denied += 1
        if "decision" in payload or ev_type == "STOP_REQUESTED": decisions += 1
    print(f"State: {fsm.state.name}\nWorkers: {len(workers)} prepared\nDepth: {max_depth}\nDecisions/Stops: {decisions}\nDenied Actions: {denied}")

if __name__ == "__main__": main()
