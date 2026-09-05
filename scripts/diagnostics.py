#!/usr/bin/env python3
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from ledger import Ledger

def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/diagnostics.py <conversation_id>")
        sys.exit(1)
        
    conv_id = sys.argv[1]
    ledger = Ledger()
    
    print(f"Diagnostics for Conversation ID: {conv_id}")
    print("-" * 50)
    
    with ledger._get_connection() as conn:
        cursor = conn.execute("SELECT event_id, type, payload, created_at FROM events WHERE event_id LIKE ? ORDER BY created_at ASC", (f"{conv_id}_%",))
        events = cursor.fetchall()
        
        if not events:
            print("No events found.")
            return
            
        for row in events:
            event_id, ev_type, payload, created_at = row
            print(f"[{created_at}] TYPE: {ev_type}")
            print(f"  EVENT_ID: {event_id}")
            print(f"  PAYLOAD: {payload}")
            print("-" * 50)

if __name__ == "__main__":
    main()
