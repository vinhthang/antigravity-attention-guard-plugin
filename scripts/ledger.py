import sqlite3
import os
import time

class Ledger:
    def __init__(self, db_path=None):
        if db_path is None:
            base_dir = os.environ.get("AGY_APP_DATA_DIR") or os.path.expanduser("~/.gemini/antigravity")
            self.db_path = os.path.join(base_dir, "attention_guard.db")
        else:
            self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
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
            
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    version INTEGER PRIMARY KEY
                );
                CREATE TABLE IF NOT EXISTS turns (
                    turn_id TEXT PRIMARY KEY,
                    status TEXT,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS tokens (
                    token_id TEXT PRIMARY KEY,
                    claimed INTEGER DEFAULT 0,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    type TEXT,
                    payload TEXT,
                    created_at REAL
                );
                CREATE TABLE IF NOT EXISTS work_items (
                    work_id TEXT PRIMARY KEY,
                    status TEXT,
                    created_at REAL
                );
            """)

    def _prune_opportunistically(self):
        # Prune expired unclaimed tokens and terminal turns older than 48 hours
        cutoff = time.time() - (48 * 3600)
        with self._get_connection() as conn:
            conn.execute("DELETE FROM tokens WHERE claimed = 0 AND created_at < ?", (cutoff,))
            conn.execute("DELETE FROM turns WHERE status = 'CLOSED' AND created_at < ?", (cutoff,))

    def claim_token(self, token_id):
        with self._get_connection() as conn:
            cursor = conn.execute("UPDATE tokens SET claimed = 1 WHERE token_id = ? AND claimed = 0", (token_id,))
            return cursor.rowcount > 0

    def insert_event(self, actor_id, turn_id, hook_type, execution_idx, work_id, event_type, payload=""):
        event_id = f"{actor_id}_{turn_id}_{hook_type}_{execution_idx}_{work_id}_{event_type}"
        with self._get_connection() as conn:
            try:
                conn.execute(
                    "INSERT INTO events (event_id, type, payload, created_at) VALUES (?, ?, ?, ?)",
                    (event_id, event_type, payload, time.time())
                )
                return True
            except sqlite3.IntegrityError:
                return False
