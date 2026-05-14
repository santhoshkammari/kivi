"""Session persistence for the Kivi CLI agent."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from .messages import Conversation, Role

__all__ = ["Session", "SQLiteSessionStore", "PromptHistory", "new_session_id", "default_store", "title_from_messages"]

DB_PATH = Path.home() / ".kivi" / "cli_sessions.db"


@dataclass
class Session:
    id: str
    title: str
    messages: list[dict]
    work_dir: str = ""
    created_at: str = ""
    updated_at: str = ""


class SQLiteSessionStore:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_tables()

    def save(self, session: Session) -> None:
        now = _now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO sessions (id, title, history, work_dir, created, updated)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET title=excluded.title, history=excluded.history, updated=excluded.updated""",
                (session.id, session.title, json.dumps(session.messages, ensure_ascii=False),
                 session.work_dir, session.created_at or now, now),
            )

    def load(self, session_id: str) -> Session | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        return self._from_row(row) if row else None

    def list_all(self) -> list[Session]:
        with self._connect() as conn:
            rows = conn.execute("SELECT id, title, work_dir, created, updated FROM sessions ORDER BY updated DESC").fetchall()
        return [self._from_row(r) for r in rows]

    def latest_for_dir(self, work_dir: str) -> Session | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM sessions WHERE work_dir = ? ORDER BY updated DESC LIMIT 1", (work_dir,)).fetchone()
        return self._from_row(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _ensure_tables(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, history TEXT NOT NULL,
                    work_dir TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS prompt_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
                    cwd TEXT NOT NULL, content TEXT NOT NULL, timestamp TEXT NOT NULL
                )
            """)

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Session:
        keys = set(row.keys())
        messages = json.loads(row["history"]) if "history" in keys else []
        return Session(
            id=row["id"], title=row["title"],
            messages=messages if isinstance(messages, list) else [],
            work_dir=row.get("work_dir", "") or "",
            created_at=row.get("created", "") or "",
            updated_at=row.get("updated", "") or "",
        )


class PromptHistory:
    def __init__(self, store: SQLiteSessionStore):
        self.store = store

    def save(self, session_id: str, cwd: str, text: str) -> None:
        if not text:
            return
        with self.store._connect() as conn:
            conn.execute(
                "INSERT INTO prompt_history (session_id, cwd, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, cwd, text, _now_iso()),
            )

    def load(self, cwd: str | None = None) -> list[str]:
        clauses, params = [], []
        if cwd:
            clauses.append("cwd = ?")
            params.append(cwd)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.store._connect() as conn:
            rows = conn.execute(f"SELECT content FROM prompt_history{where} ORDER BY id ASC", params).fetchall()
        return [row["content"] for row in rows]


def new_session_id() -> str:
    return uuid4().hex[:8]


def title_from_messages(messages: list[dict]) -> str:
    for m in messages:
        if m.get("role") == "user":
            text = m.get("content", "")
            if isinstance(text, str) and text.strip():
                t = text.strip().replace("\n", " ")[:60]
                return t + ("…" if len(text.strip()) > 60 else "")
    return "untitled"


_DEFAULT_STORE: SQLiteSessionStore | None = None


def default_store() -> SQLiteSessionStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SQLiteSessionStore()
    return _DEFAULT_STORE


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
