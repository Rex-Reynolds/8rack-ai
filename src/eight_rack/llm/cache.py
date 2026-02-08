"""SQLite response cache for LLM calls."""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class ResponseCache:
    """SQLite-backed LLM response cache.

    Keyed on a hash of (model, system, messages, response_model).
    Supports TTL-based expiration.
    """

    def __init__(self, db_path: Path, ttl_seconds: float = 86400 * 7):
        self.db_path = db_path
        self.ttl = ttl_seconds
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self.hits = 0
        self.misses = 0
        self._init_schema()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _init_schema(self) -> None:
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        self.conn.commit()

    def get(self, key: str) -> str | None:
        """Get a cached response by key. Returns None if miss or expired."""
        row = self.conn.execute(
            "SELECT value, created_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            self.misses += 1
            return None
        if time.time() - row["created_at"] > self.ttl:
            self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self.conn.commit()
            self.misses += 1
            return None
        self.hits += 1
        return row["value"]

    def put(self, key: str, value: str) -> None:
        """Store a response in the cache."""
        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, created_at) VALUES (?, ?, ?)",
            (key, value, time.time()),
        )
        self.conn.commit()

    def clear(self) -> None:
        """Clear all cached responses."""
        self.conn.execute("DELETE FROM cache")
        self.conn.commit()

    @property
    def size(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) as cnt FROM cache").fetchone()
        return row["cnt"]

    @property
    def hit_rate(self) -> float:
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None
