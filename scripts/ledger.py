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

SCHEMA_VERSION = 2
_INITIALIZED_DBS = set()
_pending_threads = []
atexit.register(lambda: [t.join(timeout=0.05) for t in list(_pending_threads) if t.is_alive()])

def _push_metric_async(event_type, payload, created_at=None):
    if os.environ.get("AGY_DISABLE_METRICS_PUSH") == "1":
        return
    if os.environ.get("ATTENTION_METRICS_PUSH_ENABLED") != "1" and not os.environ.get("ATTENTION_METRICS_API_KEY", "").strip():
        return

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
            urllib.request.urlopen(req, context=_SSL_CONTEXT, timeout=1.5)
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

class LedgerConnection(sqlite3.Connection):
    def execute(self, sql, *args):
        clean = sql.strip().rstrip(";").lower()
        if clean == "pragma case_sensitive_like":
            cur = super().execute("SELECT ('a' LIKE 'A')")
            row = cur.fetchone()
            val = 1 if (row and row[0] == 0) else 0
            return super().execute(f"SELECT {val}")
        return super().execute(sql, *args)

    def executescript(self, sql_script):
        return super().executescript(sql_script)

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
        conn = sqlite3.connect(self.db_path, timeout=5.0, factory=LedgerConnection)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA case_sensitive_like = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _init_db(self):
        abs_path = os.path.abspath(self.db_path)
        if os.path.isfile(abs_path) and os.path.getsize(abs_path) > 0:
            st = os.stat(abs_path)
            key = (abs_path, st.st_mtime_ns, st.st_size)
            if key in _INITIALIZED_DBS:
                return

        with self._get_connection() as conn:
            ver = conn.execute("PRAGMA user_version").fetchone()[0]
            if ver >= SCHEMA_VERSION:
                has_events = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'").fetchone()
                if has_events:
                    if os.path.isfile(abs_path):
                        st = os.stat(abs_path)
                        _INITIALIZED_DBS.add((abs_path, st.st_mtime_ns, st.st_size))
                    return

            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS schema_metadata (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS turns (turn_id TEXT PRIMARY KEY, status TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS tokens (token_id TEXT PRIMARY KEY, claimed INTEGER DEFAULT 0, claimed_by TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, type TEXT, payload TEXT, created_at REAL);
                CREATE TABLE IF NOT EXISTS work_items (
                    work_id TEXT PRIMARY KEY,
                    status TEXT,
                    created_at REAL,
                    parent_conv_id TEXT,
                    parent_turn_id TEXT,
                    step_idx TEXT,
                    updated_at REAL
                );
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

                CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(type, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
                CREATE INDEX IF NOT EXISTS idx_work_items_parent ON work_items(parent_conv_id, parent_turn_id, status);
                CREATE INDEX IF NOT EXISTS idx_work_items_status ON work_items(status, updated_at, created_at);
                CREATE INDEX IF NOT EXISTS idx_tokens_claimed_by ON tokens(claimed_by);
            ''')

            # Inspect columns before altering to avoid exception-driven flow
            token_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tokens)").fetchall()}
            if "claimed_by" not in token_cols:
                conn.execute("ALTER TABLE tokens ADD COLUMN claimed_by TEXT")

            work_cols = {r["name"] for r in conn.execute("PRAGMA table_info(work_items)").fetchall()}
            for col in ("parent_conv_id", "parent_turn_id", "step_idx"):
                if col not in work_cols:
                    conn.execute(f"ALTER TABLE work_items ADD COLUMN {col} TEXT")
            if "updated_at" not in work_cols:
                conn.execute("ALTER TABLE work_items ADD COLUMN updated_at REAL")

            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        if os.path.isfile(abs_path):
            st = os.stat(abs_path)
            _INITIALIZED_DBS.add((abs_path, st.st_mtime_ns, st.st_size))

    def prune(self, retention_seconds: float = 7 * 86400, transient_retention_seconds: float = 86400) -> dict:
        now = time.time()
        with self._get_connection() as conn:
            cur1 = conn.execute(
                "DELETE FROM events WHERE type IN ('SUBAGENT_COMMAND', 'SUBAGENT_FILE_EDIT') AND created_at < ?",
                (now - transient_retention_seconds,)
            )
            cur2 = conn.execute(
                "DELETE FROM events WHERE created_at < ?",
                (now - retention_seconds,)
            )
            cur3 = conn.execute(
                "DELETE FROM work_items WHERE status IN ('COMPLETED', 'TERMINATED', 'DONE', 'FAILED', 'TIMED_OUT') AND COALESCE(updated_at, created_at) < ?",
                (now - retention_seconds,)
            )
            cur4 = conn.execute(
                "DELETE FROM tokens WHERE created_at < ?",
                (now - retention_seconds,)
            )
            cur5 = conn.execute(
                "DELETE FROM turns WHERE status = 'CLOSED' AND created_at < ?",
                (now - retention_seconds,)
            )
            conn.commit()
            return {
                "events_deleted": cur1.rowcount + cur2.rowcount,
                "work_items_deleted": cur3.rowcount,
                "tokens_deleted": cur4.rowcount,
                "turns_deleted": cur5.rowcount,
            }

    def _prune_opportunistically(self, min_interval_seconds: float = 3600.0):
        marker = f"{self.db_path}.last_prune"
        try:
            if os.path.exists(marker):
                mtime = os.path.getmtime(marker)
                if (time.time() - mtime) < min_interval_seconds:
                    return
            self.prune()
            with open(marker, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except Exception:
            return


    def reconcile_orphaned_work_items(self, parent_conv_id: str, parent_turn_id: str, current_step_idx: str | None = None) -> int:
        now = time.time()
        terminated_count = 0
        with self._get_connection() as conn:
            rows = conn.execute(
                """
                SELECT w.work_id, w.step_idx, COALESCE(t.claimed, 0) as claimed
                FROM work_items w
                LEFT JOIN tokens t ON w.work_id = t.token_id
                WHERE w.parent_conv_id = ? AND w.parent_turn_id = ? AND w.status = 'ACTIVE'
                """,
                (parent_conv_id, str(parent_turn_id)),
            ).fetchall()

            for row in rows:
                work_id = row["work_id"]
                step_idx = str(row["step_idx"]) if row["step_idx"] is not None else ""
                claimed = row["claimed"]

                if claimed != 0:
                    continue

                if current_step_idx is not None and str(step_idx) == str(current_step_idx):
                    continue

                prep_event_id = f"{parent_conv_id}_{parent_turn_id}_PreToolUse_{step_idx}_{work_id}_WORK_PREPARED"
                has_prep = conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (prep_event_id,)
                ).fetchone()

                handoff_event_id = f"{parent_conv_id}_{parent_turn_id}_PostToolUse_{step_idx}_invoke_HANDOFF_ACCEPTED"
                has_handoff = conn.execute(
                    "SELECT 1 FROM events WHERE event_id = ?",
                    (handoff_event_id,)
                ).fetchone()

                if (has_prep or step_idx != "") and not has_handoff:
                    conn.execute(
                        "UPDATE work_items SET status = 'TERMINATED', updated_at = ? WHERE work_id = ?",
                        (now, work_id),
                    )
                    terminated_count += 1

            if terminated_count > 0:
                conn.commit()
        return terminated_count

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
                if event_type in ("WORK_PREPARED", "STOP_REQUESTED", "TURN_CLOSED") and actor_id != "unknown":
                    turn_status = "CLOSED" if event_type == "TURN_CLOSED" else ("EXECUTION_ACTIVE" if event_type == "WORK_PREPARED" else "STOP_REQUESTED")
                    turn_key = f"{actor_id}_{turn_id}"
                    conn.execute(
                        """
                        INSERT INTO turns (turn_id, status, created_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(turn_id) DO UPDATE SET status = excluded.status
                        """,
                        (turn_key, turn_status, now)
                    )
                if event_type in ("PRIMARY_TOOL_DENIED", "STOP_REQUESTED"):
                    _push_metric_async(event_type, payload, now)
                return True
            except sqlite3.IntegrityError:
                return False

    def sync_session_chars(self, session_id: str, total_chars: int):
        now = time.time()
        with self._get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT total_session_chars, chars_since_refresh FROM session_stats WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO session_stats (session_id, total_session_chars, chars_since_refresh, updated_at) VALUES (?, ?, ?, ?)",
                    (session_id, total_chars, total_chars, now),
                )
            else:
                prev_total = row[0] or 0
                prev_since = row[1] or 0
                new_total = max(prev_total, total_chars)
                delta = max(0, total_chars - prev_total)
                conn.execute(
                    "UPDATE session_stats SET total_session_chars = ?, chars_since_refresh = ?, updated_at = ? WHERE session_id = ?",
                    (new_total, prev_since + delta, now, session_id),
                )
            conn.commit()

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

    def audit_conversation_budget(self, conv_id: str) -> dict:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE event_id LIKE ? AND type = 'WORK_PREPARED' ORDER BY created_at ASC",
                (f"{conv_id}_%",)
            ).fetchall()
            total_events_row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_id LIKE ?",
                (f"{conv_id}_%",)
            ).fetchone()
            total_events = total_events_row[0] if total_events_row else 0
            tokens = []
            for r in rows:
                p_str = r[0] if r else None
                if p_str:
                    try:
                        p_data = json.loads(p_str) if isinstance(p_str, str) else p_str
                        t = p_data.get("token")
                        if t:
                            tokens.append(t)
                    except Exception as exc:
                        _ = exc
            duplicate_tokens = sorted({t for t in tokens if t and tokens.count(t) > 1})
            return {
                "prepared_workers": len(tokens),
                "unique_workers": len(set(tokens)),
                "duplicate_tokens": duplicate_tokens,
                "budget_ok": len(duplicate_tokens) == 0,
                "total_events": total_events,
            }

