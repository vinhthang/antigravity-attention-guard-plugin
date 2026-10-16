import sqlite3
import os
import time
import threading
import urllib.request
import json
import atexit

try:
    import certifi
    import ssl
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CONTEXT = None

_pending_threads = []
atexit.register(lambda: [t.join(timeout=1.0) for t in _pending_threads if t.is_alive()])

def _push_metric_async(event_type, payload, created_at=None):
    def _post():
        try:
            server_url = os.environ.get(
                "ATTENTION_METRICS_SERVER_URL",
                "https://attention-metrics-server.vinhthang.dev/api/metrics"
            )
            api_key = os.environ.get("ATTENTION_METRICS_API_KEY", "")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "AttentionGuard/antigravity"
            }
            if api_key:
                headers["X-API-Key"] = api_key

            body = {
                "event_type": event_type,
                "platform": "antigravity",
                "payload": payload
            }
            if created_at is not None:
                # ISO 8601 format
                if isinstance(created_at, (int, float)):
                    from datetime import datetime, timezone
                    body["created_at"] = datetime.fromtimestamp(created_at, timezone.utc).isoformat()
                elif isinstance(created_at, str):
                    body["created_at"] = created_at

            data = json.dumps(body).encode("utf-8")
            req = urllib.request.Request(
                server_url,
                data=data,
                headers=headers,
                method="POST"
            )
            urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=5)
        except Exception:
            return
        finally:
            try:
                _pending_threads.remove(t)
            except ValueError as exc:
                _ = exc

    t = threading.Thread(target=_post, daemon=True)
    _pending_threads.append(t)
    t.start()

class Ledger:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
            self.db_path = os.path.join(base_dir, "attention_guard.db")
        else:
            self.db_path = db_path
        dir_name = os.path.dirname(self.db_path)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        self._init_db()
        self._prune_opportunistically()

    def _get_connection(self):
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA busy_timeout=5000")
            
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS schema_metadata (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS turns (turn_id TEXT PRIMARY KEY, status TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS tokens (token_id TEXT PRIMARY KEY, claimed INTEGER DEFAULT 0, claimed_by TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS work_items (work_id TEXT PRIMARY KEY, status TEXT, created_at REAL, parent_conv_id TEXT, parent_turn_id TEXT, step_idx TEXT);
                CREATE TABLE IF NOT EXISTS session_stats (
                    session_id TEXT PRIMARY KEY,
                    total_session_chars INTEGER DEFAULT 0,
                    chars_since_refresh INTEGER DEFAULT 0,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS session_refresh_state (
                    session_id TEXT PRIMARY KEY,
                    last_refreshed_tokens INTEGER DEFAULT 0,
                    updated_at REAL
                );
            ''')
            for alter_stmt in [
                "ALTER TABLE tokens ADD COLUMN claimed_by TEXT",
                "ALTER TABLE work_items ADD COLUMN parent_conv_id TEXT",
                "ALTER TABLE work_items ADD COLUMN parent_turn_id TEXT",
                "ALTER TABLE work_items ADD COLUMN step_idx TEXT",
                "ALTER TABLE work_items ADD COLUMN updated_at REAL"
            ]:
                try:
                    conn.execute(alter_stmt)
                except sqlite3.OperationalError as exc:
                    if "duplicate column name" not in str(exc).lower():
                        raise

    def _prune_opportunistically(self):
        pass

    def claim_token(self, token_id, conv_id):
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE tokens SET claimed = 1, claimed_by = ? WHERE token_id = ? AND claimed = 0", (conv_id, token_id))
            if cursor.rowcount > 0: return True
            cursor = conn.execute("SELECT claimed, claimed_by FROM tokens WHERE token_id = ?", (token_id,))
            row = cursor.fetchone()
            if row and row[0]:
                if row[1] == conv_id: return True
                if row[1] is None:
                    cursor = conn.execute("UPDATE tokens SET claimed_by = ? WHERE token_id = ? AND claimed_by IS NULL", (conv_id, token_id))
                    return cursor.rowcount > 0
            return False

    def insert_event(self, actor_id, turn_id, hook_type, execution_idx, work_id, event_type, payload=""):
        event_id = f"{actor_id}_{turn_id}_{hook_type}_{execution_idx}_{work_id}_{event_type}"
        now = time.time()
        with self._get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, event_type, payload, now)
                )
                if event_type in ("PRIMARY_TOOL_DENIED", "STOP_REQUESTED"):
                    _push_metric_async(event_type, payload, now)
                return True
            except sqlite3.IntegrityError:
                return False

    def record_tool_chars(self, session_id: str, chars: int):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_stats (session_id, total_session_chars, chars_since_refresh, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    total_session_chars = total_session_chars + excluded.total_session_chars,
                    chars_since_refresh = chars_since_refresh + excluded.chars_since_refresh,
                    updated_at = excluded.updated_at
                """,
                (session_id, chars, chars, now)
            )

    def get_session_token_stats(self, session_id: str) -> tuple[int, int]:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT total_session_chars, chars_since_refresh FROM session_stats WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row:
                total_chars = row[0] if row[0] is not None else 0
                refresh_chars = row[1] if row[1] is not None else 0
                return (total_chars // 4, refresh_chars // 4)
            return (0, 0)

    def reset_refresh_counter(self, session_id: str):
        with self._get_connection() as conn:
            conn.execute(
                "UPDATE session_stats SET chars_since_refresh = 0 WHERE session_id = ?",
                (session_id,)
            )

    def get_last_refreshed_tokens(self, session_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT last_refreshed_tokens FROM session_refresh_state WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if row and row[0] is not None:
                return int(row[0])
            return 0

    def record_refresh(self, session_id: str, current_tokens: int):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO session_refresh_state (session_id, last_refreshed_tokens, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    last_refreshed_tokens = excluded.last_refreshed_tokens,
                    updated_at = excluded.updated_at
                """,
                (session_id, current_tokens, now)
            )

