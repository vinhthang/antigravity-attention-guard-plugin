#!/usr/bin/env python3
"""
Sync local SQLite attention-guard events to attention-metrics-server.
"""
import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    import certifi
    import ssl
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = None

DEFAULT_EVENT_TYPES = ("PRIMARY_TOOL_DENIED", "STOP_REQUESTED", "TURN_CLOSED")
DEFAULT_SERVER_URL = "https://attention-metrics-server.vinhthang.dev/api/metrics"
DEFAULT_BATCH_SIZE = 50


def get_default_db_path() -> str:
    base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
    return os.path.join(base_dir, "attention_guard.db")


def format_iso_timestamp(created_at: Any) -> str:
    if isinstance(created_at, (int, float)):
        return datetime.fromtimestamp(created_at, timezone.utc).isoformat()
    if isinstance(created_at, str):
        return created_at
    return datetime.now(timezone.utc).isoformat()


def fetch_events(
    db_path: str,
    sync_all: bool = False,
    limit: Optional[int] = None
) -> List[Dict[str, Any]]:
    if not os.path.isfile(db_path):
        return []

    conn = sqlite3.connect(db_path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        if sync_all:
            query = "SELECT event_id, type, payload, created_at FROM events ORDER BY created_at ASC"
            params: Tuple[Any, ...] = ()
        else:
            placeholders = ",".join(["?"] * len(DEFAULT_EVENT_TYPES))
            query = f"SELECT event_id, type, payload, created_at FROM events WHERE type IN ({placeholders}) ORDER BY created_at ASC"
            params = DEFAULT_EVENT_TYPES

        if limit is not None and limit > 0:
            query += f" LIMIT {int(limit)}"

        cursor.execute(query, params)
        rows = cursor.fetchall()
        return [dict(r) for r in rows]
    except sqlite3.OperationalError as exc:
        print(f"Warning: SQLite query failed: {exc}", file=sys.stderr)
        return []
    finally:
        conn.close()


def send_metric_event(
    server_url: str,
    event_type: str,
    payload: Any,
    created_at_iso: str,
    headers: Dict[str, str]
) -> Tuple[bool, str]:
    body = {
        "event_type": event_type,
        "payload": payload,
        "created_at": created_at_iso
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        server_url,
        data=data,
        headers=headers,
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=10) as resp:
            status = resp.status
            if status in (200, 201):
                return True, f"HTTP {status}"
            return False, f"Unexpected HTTP {status}"
    except urllib.error.HTTPError as err:
        err_msg = f"HTTP {err.code}: {err.reason}"
        try:
            err_body = err.read().decode("utf-8", errors="replace")
            if err_body:
                err_msg += f" - {err_body}"
        except Exception as read_exc:
            _ = read_exc
        return False, err_msg
    except Exception as exc:
        return False, str(exc)


def sync_events(
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = False,
    sync_all: bool = False,
    server_url: Optional[str] = None,
    api_key: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE
) -> Dict[str, int]:
    actual_db_path = db_path or get_default_db_path()
    actual_server_url = server_url or os.environ.get("ATTENTION_METRICS_SERVER_URL", DEFAULT_SERVER_URL)
    actual_api_key = api_key if api_key is not None else os.environ.get("ATTENTION_METRICS_API_KEY", "")

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "AttentionGuard/1.0"
    }
    if actual_api_key:
        headers["X-API-Key"] = actual_api_key

    if not os.path.exists(actual_db_path):
        print(f"Database not found at '{actual_db_path}'. Nothing to sync.")
        return {"total": 0, "synced": 0, "failed": 0, "batches": 0}

    print(f"Reading events from: {actual_db_path}")
    events = fetch_events(actual_db_path, sync_all=sync_all, limit=limit)
    total_events = len(events)
    print(f"Found {total_events} events matching filter (all={sync_all}, limit={limit}).")

    if total_events == 0:
        return {"total": 0, "synced": 0, "failed": 0, "batches": 0}

    batches = [events[i:i + batch_size] for i in range(0, total_events, batch_size)]
    synced_count = 0
    failed_count = 0

    print(f"Syncing {total_events} events across {len(batches)} batch(es) of up to {batch_size} items...")

    for b_idx, batch in enumerate(batches, 1):
        print(f"\n--- Batch {b_idx}/{len(batches)} ({len(batch)} items) ---")
        for item in batch:
            event_id = item.get("event_id", "unknown")
            event_type = item.get("type", "UNKNOWN")
            raw_payload = item.get("payload", "")
            raw_created_at = item.get("created_at")

            # Parse payload if json
            if isinstance(raw_payload, str):
                try:
                    payload = json.loads(raw_payload)
                except Exception as exc:
                    _ = exc
                    payload = raw_payload
            else:
                payload = raw_payload

            iso_created_at = format_iso_timestamp(raw_created_at)

            if dry_run:
                print(f"  [DRY-RUN] Would sync {event_type} (id: {event_id}, timestamp: {iso_created_at})")
                synced_count += 1
            else:
                ok, msg = send_metric_event(actual_server_url, event_type, payload, iso_created_at, headers)
                if ok:
                    synced_count += 1
                    print(f"  [OK] Synced {event_type} (id: {event_id}) -> {msg}")
                else:
                    failed_count += 1
                    print(f"  [ERROR] Failed to sync {event_type} (id: {event_id}): {msg}", file=sys.stderr)

    print(f"\nSync summary: {synced_count} synced, {failed_count} failed out of {total_events} total events.")
    return {
        "total": total_events,
        "synced": synced_count,
        "failed": failed_count,
        "batches": len(batches)
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync local Attention Guard SQLite events to attention-metrics-server.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of events to sync")
    parser.add_argument("--dry-run", action="store_true", help="Print items to be synced without making network requests")
    parser.add_argument("--all", action="store_true", dest="sync_all", help="Sync all event types (default: PRIMARY_TOOL_DENIED, STOP_REQUESTED, TURN_CLOSED)")
    parser.add_argument("--db-path", default=None, help="Path to attention_guard.db (default: ~/.gemini/antigravity/attention_guard.db)")
    parser.add_argument("--server-url", default=None, help=f"Destination server endpoint (default: {DEFAULT_SERVER_URL})")
    parser.add_argument("--api-key", default=None, help="API key for authentication (default: ATTENTION_METRICS_API_KEY env)")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help=f"Batch size (default: {DEFAULT_BATCH_SIZE})")

    args = parser.parse_args()

    results = sync_events(
        db_path=args.db_path,
        limit=args.limit,
        dry_run=args.dry_run,
        sync_all=args.sync_all,
        server_url=args.server_url,
        api_key=args.api_key,
        batch_size=args.batch_size
    )

    if results["failed"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
