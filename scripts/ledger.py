import atexit
import json
import os
import sqlite3
import time

SCHEMA_VERSION = 3
_INITIALIZED_DBS = set()
_pending_threads = []
_SSL_CONTEXT = None
_SSL_INITIALIZED = False
atexit.register(lambda: [t.join(timeout=0.05) for t in list(_pending_threads) if t.is_alive()])


def _get_ssl_context():
    global _SSL_CONTEXT, _SSL_INITIALIZED
    if not _SSL_INITIALIZED:
        _SSL_INITIALIZED = True
        try:
            import certifi
            import ssl
            _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
        except Exception as exc:
            _ = exc
            _SSL_CONTEXT = None
    return _SSL_CONTEXT


def _push_metric_async(event_type, payload, created_at=None):
    if os.environ.get("AGY_DISABLE_METRICS_PUSH") == "1":
        return
    if os.environ.get("ATTENTION_METRICS_PUSH_ENABLED") != "1" and not os.environ.get("ATTENTION_METRICS_API_KEY", "").strip():
        return

    import threading
    import urllib.request

    def _post():
        try:
            server_url = os.environ.get(
                "ATTENTION_METRICS_SERVER_URL",
                "https://attention-metrics-server.vinhthang.dev/api/metrics",
            )
            api_key = os.environ.get("ATTENTION_METRICS_API_KEY", "")
            headers = {
                "Content-Type": "application/json",
                "User-Agent": "AttentionGuard/antigravity",
            }
            if api_key:
                headers["X-API-Key"] = api_key

            body = {
                "event_type": event_type,
                "platform": "antigravity",
                "payload": payload,
            }
            if created_at is not None:
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
                method="POST",
            )
            urllib.request.urlopen(req, context=_get_ssl_context(), timeout=1.5)
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
                has_events = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='events'"
                ).fetchone()
                has_tokens = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tokens'"
                ).fetchone()
                if has_events and has_tokens:
                    if os.path.isfile(abs_path):
                        st = os.stat(abs_path)
                        _INITIALIZED_DBS.add((abs_path, st.st_mtime_ns, st.st_size))
                    return

            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")

            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (version INTEGER PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS tokens (
                    token_id TEXT PRIMARY KEY,
                    claimed INTEGER DEFAULT 0,
                    claimed_by TEXT,
                    may_delegate INTEGER DEFAULT 0,
                    remaining_depth INTEGER DEFAULT 0,
                    parent_conv_id TEXT,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    type TEXT,
                    payload TEXT,
                    created_at REAL
                );

                CREATE INDEX IF NOT EXISTS idx_events_type_created ON events(type, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
                CREATE INDEX IF NOT EXISTS idx_tokens_claimed_by ON tokens(claimed_by);
                """
            )

            token_cols = {r["name"] for r in conn.execute("PRAGMA table_info(tokens)").fetchall()}
            migrations = (
                ("claimed_by", "TEXT"),
                ("may_delegate", "INTEGER DEFAULT 0"),
                ("remaining_depth", "INTEGER DEFAULT 0"),
                ("parent_conv_id", "TEXT"),
            )
            for col_name, col_def in migrations:
                if col_name not in token_cols:
                    conn.execute(f"ALTER TABLE tokens ADD COLUMN {col_name} {col_def}")

            conn.execute("INSERT OR IGNORE INTO schema_metadata (version) VALUES (?)", (SCHEMA_VERSION,))
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        if os.path.isfile(abs_path):
            st = os.stat(abs_path)
            _INITIALIZED_DBS.add((abs_path, st.st_mtime_ns, st.st_size))

    def prune(self, retention_seconds: float = 7 * 86400, transient_retention_seconds: float = 86400) -> dict:
        now = time.time()
        with self._get_connection() as conn:
            cur1 = conn.execute(
                "DELETE FROM events WHERE type IN ('SUBAGENT_COMMAND', 'SUBAGENT_FILE_EDIT') AND created_at < ?",
                (now - transient_retention_seconds,),
            )
            cur2 = conn.execute(
                "DELETE FROM events WHERE created_at < ?",
                (now - retention_seconds,),
            )
            cur3 = conn.execute(
                "DELETE FROM tokens WHERE created_at < ?",
                (now - retention_seconds,),
            )
            conn.commit()
            return {
                "events_deleted": cur1.rowcount + cur2.rowcount,
                "tokens_deleted": cur3.rowcount,
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

    def issue_token(
        self,
        token_id: str,
        may_delegate: bool = False,
        remaining_depth: int = 0,
        parent_conv_id: str = "",
    ) -> None:
        now = time.time()
        with self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO tokens (token_id, claimed, claimed_by, may_delegate, remaining_depth, parent_conv_id, created_at)
                VALUES (?, 0, NULL, ?, ?, ?, ?)
                """,
                (token_id, 1 if may_delegate else 0, int(remaining_depth), parent_conv_id or "", now),
            )
            conn.commit()

    def get_token(self, token_id: str) -> dict | None:
        if not token_id:
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT token_id, claimed, claimed_by, may_delegate, remaining_depth, parent_conv_id, created_at "
                "FROM tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def get_claimed_token_by_conv(self, conv_id: str) -> dict | None:
        if not conv_id or conv_id == "unknown":
            return None
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT token_id, claimed, claimed_by, may_delegate, remaining_depth, parent_conv_id, created_at "
                "FROM tokens WHERE claimed = 1 AND claimed_by = ? ORDER BY created_at DESC LIMIT 1",
                (conv_id,),
            ).fetchone()
            return dict(row) if row is not None else None

    def claim_token(self, token_id, conv_id):
        with self._get_connection() as conn:
            cursor = conn.execute(
                "UPDATE tokens SET claimed = 1, claimed_by = ? WHERE token_id = ? AND claimed = 0",
                (conv_id, token_id),
            )
            if cursor.rowcount > 0:
                return True
            cursor = conn.execute("SELECT claimed, claimed_by FROM tokens WHERE token_id = ?", (token_id,))
            row = cursor.fetchone()
            if row and row[0]:
                if row[1] == conv_id:
                    return True
                if row[1] is None:
                    cursor = conn.execute(
                        "UPDATE tokens SET claimed_by = ? WHERE token_id = ? AND claimed_by IS NULL",
                        (conv_id, token_id),
                    )
                    return cursor.rowcount > 0
            return False

    def insert_event(self, actor_id, turn_id, hook_type, execution_idx, work_id, event_type, payload=""):
        event_id = f"{actor_id}_{turn_id}_{hook_type}_{execution_idx}_{work_id}_{event_type}"
        now = time.time()
        with self._get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, event_type, payload, now),
                )
                if event_type in ("PRIMARY_TOOL_DENIED", "STOP_REQUESTED"):
                    _push_metric_async(event_type, payload, now)
                return True
            except sqlite3.IntegrityError:
                return False

    def audit_conversation_budget(self, conv_id: str) -> dict:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT payload FROM events WHERE event_id LIKE ? AND type = 'WORK_PREPARED' ORDER BY created_at ASC",
                (f"{conv_id}_%",),
            ).fetchall()
            total_events_row = conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_id LIKE ?",
                (f"{conv_id}_%",),
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
