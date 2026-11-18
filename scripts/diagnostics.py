#!/usr/bin/env python3
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(__file__))


def _empty_metrics() -> dict:
    return {
        "PRIMARY_TOOL_DENIED": 0,
        "primary_denials": 0,
        "subagent_denials": 0,
        "denials_by_tool": {},
    }


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
        if args.metrics:
            if args.json:
                print(json.dumps(_empty_metrics()))
            else:
                print("No database found.")
        else:
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

    try:
        if args.metrics:
            try:
                rows = conn.execute(
                    "SELECT payload FROM events WHERE type = 'PRIMARY_TOOL_DENIED'"
                ).fetchall()
                metrics_data = _empty_metrics()
                for r in rows:
                    metrics_data["PRIMARY_TOOL_DENIED"] += 1
                    payload_raw = r[0]
                    payload = {}
                    if payload_raw:
                        try:
                            parsed = json.loads(payload_raw)
                            if isinstance(parsed, dict):
                                payload = parsed
                        except Exception as exc:
                            _ = exc
                    if payload.get("is_sub") is True:
                        metrics_data["subagent_denials"] += 1
                    else:
                        metrics_data["primary_denials"] += 1
                    tool_name = payload.get("tool")
                    if tool_name:
                        by_tool = metrics_data["denials_by_tool"]
                        by_tool[tool_name] = by_tool.get(tool_name, 0) + 1

                if args.json:
                    print(json.dumps(metrics_data))
                else:
                    print("Metrics:")
                    print(f"  PRIMARY_TOOL_DENIED: {metrics_data['PRIMARY_TOOL_DENIED']}")
                    print(f"  primary_denials:     {metrics_data['primary_denials']}")
                    print(f"  subagent_denials:    {metrics_data['subagent_denials']}")
                    print(f"  denials_by_tool:     {metrics_data['denials_by_tool']}")
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
            events = conn.execute(
                "SELECT event_id, type, payload, created_at FROM events WHERE event_id LIKE ? ORDER BY created_at ASC",
                (f"{conv_id}_%",),
            ).fetchall()
        except sqlite3.Error as e:
            if args.json:
                print(json.dumps({"error": f"Database query error: {e}"}))
            else:
                print(f"Database query error: {e}")
            return

        if not events:
            if args.json:
                print(json.dumps({}))
            else:
                print("No events found.")
            return

        workers = set()
        worker_tokens = []
        max_depth = 0
        denied = 0
        breaker_trips = 0
        for row in events:
            _, ev_type, payload_str, _ = row
            payload = {}
            if payload_str:
                try:
                    parsed = json.loads(payload_str)
                    if isinstance(parsed, dict):
                        payload = parsed
                except Exception as exc:
                    _ = exc
            if ev_type == "WORK_PREPARED":
                tok = payload.get("token")
                if tok:
                    workers.add(tok)
                    worker_tokens.append(tok)
                max_depth = max(max_depth, int(payload.get("remaining_depth", 0) or 0))
            elif ev_type == "PRIMARY_TOOL_DENIED":
                denied += 1
            elif ev_type == "BREAKER_STATE_CHANGE":
                breaker_trips += 1

        duplicate_tokens = sorted({t for t in worker_tokens if t and worker_tokens.count(t) > 1})
        budget_ok = len(duplicate_tokens) == 0

        res = {
            "workers": len(workers),
            "depth": max_depth,
            "denied_actions": denied,
            "breaker_trips": breaker_trips,
            "duplicate_tokens": duplicate_tokens,
            "budget_ok": budget_ok,
        }

        if args.json:
            print(json.dumps(res))
        else:
            print(
                f"Workers: {len(workers)} prepared\n"
                f"Depth: {max_depth}\n"
                f"Denied Actions: {denied}\n"
                f"Breaker Trips: {breaker_trips}\n"
                f"Duplicate Tokens: {duplicate_tokens}\n"
                f"Budget OK: {budget_ok}"
            )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
