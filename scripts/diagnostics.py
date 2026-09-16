#!/usr/bin/env python3
import sys, os, json, sqlite3
import argparse
sys.path.insert(0, os.path.dirname(__file__))
from fsm import FSM, Event

def main():
    parser = argparse.ArgumentParser(description="Diagnostics tool")
    parser.add_argument("conv_id", nargs="?", help="Conversation ID")
    parser.add_argument("--metrics", action="store_true", help="Show system-wide metrics")
    parser.add_argument("--json", action="store_true", help="Output in JSON")
    args = parser.parse_args()

    if not args.conv_id and not args.metrics:
        print("Usage: python scripts/diagnostics.py <conversation_id> [options]")
        sys.exit(1)

    base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
    db_path = os.path.join(base_dir, "attention_guard.db")
    if not os.path.exists(db_path):
        if args.json:
            print(json.dumps({}))
        else:
            print("No database found.")
        return
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        if args.json:
            print(json.dumps({"error": str(e)}))
        else:
            print(f"Database error: {e}")
        return

    if args.metrics:
        try:
            query = "SELECT type, COUNT(*) as count FROM events WHERE type IN ('PRIMARY_TOOL_DENIED', 'STOP_REQUESTED') GROUP BY type"
            rows = conn.execute(query).fetchall()
            metrics_data = {"PRIMARY_TOOL_DENIED": 0, "STOP_REQUESTED": 0}
            for r in rows:
                metrics_data[r[0]] = r[1]
                
            if args.json:
                print(json.dumps(metrics_data))
            else:
                print("Metrics:")
                print(f"  PRIMARY_TOOL_DENIED: {metrics_data['PRIMARY_TOOL_DENIED']}")
                print(f"  STOP_REQUESTED:      {metrics_data['STOP_REQUESTED']}")
            return
        except sqlite3.Error as e:
            if args.json:
                print(json.dumps({"error": f"Database query error: {e}"}))
            else:
                print(f"Database query error: {e}")
            return

    conv_id = args.conv_id
    if not args.json:
        print(f"Diagnostics for Conversation ID: {conv_id}\n" + "-" * 50)
    try:
        events = conn.execute("SELECT event_id, type, payload, created_at FROM events WHERE event_id LIKE ? ORDER BY created_at ASC", (f"{conv_id}_%",)).fetchall()
    except sqlite3.Error as e:
        if args.json: print(json.dumps({"error": f"Database query error: {e}"}))
        else: print(f"Database query error: {e}")
        return
        
    if not events: 
        if args.json: print(json.dumps({}))
        else: print("No events found.")
        return

    fsm = FSM()
    workers = set()
    max_depth = 0
    decisions = 0
    denied = 0
    for row in events:
        event_id, ev_type, payload_str, created_at = row
        payload = json.loads(payload_str) if payload_str else {}
        try: fsm.transition(Event[ev_type], payload)
        except KeyError as exc: 
            if not args.json: sys.stderr.write(f"Warning: Unknown event {ev_type}: {exc}\n")
        if ev_type == "WORK_PREPARED":
            workers.add(payload.get("token"))
            max_depth = max(max_depth, payload.get("remaining_depth", 0))
        if ev_type == "PRIMARY_TOOL_DENIED": denied += 1
        if "decision" in payload or ev_type == "STOP_REQUESTED": decisions += 1
        
    res = {
        "state": fsm.state.name,
        "workers": len(workers),
        "depth": max_depth,
        "decisions_stops": decisions,
        "denied_actions": denied
    }
    
    if args.json:
        print(json.dumps(res))
    else:
        print(f"State: {fsm.state.name}\nWorkers: {len(workers)} prepared\nDepth: {max_depth}\nDecisions/Stops: {decisions}\nDenied Actions: {denied}")

if __name__ == "__main__":
    main()
