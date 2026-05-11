"""SQLite session store — provider-agnostic persistence."""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from ..core.interfaces import SessionStore
from ..core.types import Message, Role

DB_PATH = os.path.expanduser("~/.unified-chat/sessions.db")

# Dedicated thread pool for DB ops to avoid blocking the event loop
_db_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="db")


class SQLiteSessionStore(SessionStore):

    def __init__(self, db_path: str = DB_PATH):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._db_path)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    async def _run(self, fn, *args):
        """Run a sync function in the thread pool to avoid blocking the event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(_db_executor, partial(fn, *args))

    def _init_db(self) -> None:
        con = self._conn()
        con.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT 'Untitled',
                provider TEXT NOT NULL DEFAULT 'openai',
                model TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                msg_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                thinking TEXT,
                tool_calls TEXT,
                tool_results TEXT,
                metadata TEXT DEFAULT '{}',
                timestamp REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, seq);

            CREATE TABLE IF NOT EXISTS token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                model TEXT,
                input_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS compaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                original_count INTEGER,
                compacted_count INTEGER,
                tokens_before INTEGER,
                tokens_after INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
        """)
        con.commit()
        con.close()

    # ── Sync internals (run in thread pool) ────────────────────────

    def _sync_create_session(self, session_id: str, title: str, provider: str, model: str) -> None:
        now = time.time()
        con = self._conn()
        con.execute(
            "INSERT INTO sessions (id, title, provider, model, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (session_id, title, provider, model, now, now),
        )
        con.commit()
        con.close()

    def _sync_get_session(self, session_id: str) -> dict | None:
        con = self._conn()
        row = con.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not row:
            con.close()
            return None
        usage = con.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) as total_tokens, "
            "COALESCE(SUM(cost_usd), 0) as cost FROM token_usage WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        msg_count = con.execute(
            "SELECT COUNT(*) as c FROM messages WHERE session_id = ? AND role = 'user'",
            (session_id,),
        ).fetchone()["c"]
        con.close()
        return {
            **dict(row),
            "total_tokens": usage["total_tokens"],
            "cost_usd": round(usage["cost"], 6),
            "msg_count": msg_count,
        }

    def _sync_list_sessions(self) -> list[dict]:
        con = self._conn()
        rows = con.execute("""
            SELECT s.*,
                COALESCE((SELECT SUM(input_tokens + output_tokens) FROM token_usage WHERE session_id = s.id), 0) as total_tokens,
                COALESCE((SELECT SUM(cost_usd) FROM token_usage WHERE session_id = s.id), 0) as cost_usd,
                (SELECT COUNT(*) FROM messages WHERE session_id = s.id AND role = 'user') as msg_count
            FROM sessions s ORDER BY s.updated_at DESC
        """).fetchall()
        con.close()
        return [dict(r) for r in rows]

    _ALLOWED_SESSION_FIELDS = frozenset({"title", "provider", "model", "updated_at"})

    def _sync_update_session(self, session_id: str, **fields: Any) -> None:
        safe_fields = {k: v for k, v in fields.items() if k in self._ALLOWED_SESSION_FIELDS}
        safe_fields["updated_at"] = time.time()
        sets = ", ".join(f"{k} = ?" for k in safe_fields)
        vals = list(safe_fields.values()) + [session_id]
        con = self._conn()
        con.execute(f"UPDATE sessions SET {sets} WHERE id = ?", vals)
        con.commit()
        con.close()

    def _sync_delete_session(self, session_id: str) -> None:
        con = self._conn()
        con.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        con.commit()
        con.close()

    def _sync_add_message(self, session_id: str, message: Message) -> None:
        con = self._conn()
        con.execute(
            "INSERT INTO messages (session_id, msg_id, seq, role, content, thinking, tool_calls, tool_results, metadata, timestamp) "
            "SELECT ?, ?, COALESCE(MAX(seq), -1) + 1, ?, ?, ?, ?, ?, ?, ? FROM messages WHERE session_id = ?",
            (
                session_id, message.id, message.role.value, message.content, message.thinking,
                json.dumps([tc.__dict__ for tc in message.tool_calls]) if message.tool_calls else None,
                json.dumps([tr.__dict__ for tr in message.tool_results]) if message.tool_results else None,
                json.dumps(message.metadata), message.timestamp, session_id,
            ),
        )
        con.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (time.time(), session_id))
        con.commit()
        con.close()

    def _sync_get_messages(self, session_id: str) -> list[Message]:
        con = self._conn()
        rows = con.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY seq", (session_id,),
        ).fetchall()
        con.close()
        from ..core.types import ToolCall, ToolResult
        messages = []
        for r in rows:
            tc = json.loads(r["tool_calls"]) if r["tool_calls"] else None
            tr = json.loads(r["tool_results"]) if r["tool_results"] else None
            messages.append(Message(
                role=Role(r["role"]), content=r["content"], thinking=r["thinking"],
                tool_calls=[ToolCall(**t) for t in tc] if tc else None,
                tool_results=[ToolResult(**t) for t in tr] if tr else None,
                metadata=json.loads(r["metadata"]) if r["metadata"] else {},
                id=r["msg_id"], timestamp=r["timestamp"],
            ))
        return messages

    def _sync_replace_messages(self, session_id: str, messages: list[Message]) -> None:
        con = self._conn()
        con.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for seq, msg in enumerate(messages):
            con.execute(
                "INSERT INTO messages (session_id, msg_id, seq, role, content, thinking, tool_calls, tool_results, metadata, timestamp) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id, msg.id, seq, msg.role.value, msg.content, msg.thinking,
                    json.dumps([tc.__dict__ for tc in msg.tool_calls]) if msg.tool_calls else None,
                    json.dumps([tr.__dict__ for tr in msg.tool_results]) if msg.tool_results else None,
                    json.dumps(msg.metadata), msg.timestamp,
                ),
            )
        con.commit()
        con.close()

    def _sync_log_usage(self, session_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        con = self._conn()
        con.execute(
            "INSERT INTO token_usage (session_id, model, input_tokens, output_tokens, cost_usd) VALUES (?,?,?,?,?)",
            (session_id, model, input_tokens, output_tokens, cost_usd),
        )
        con.commit()
        con.close()

    def _sync_log_compaction(self, session_id: str, original_count: int, compacted_count: int,
                             tokens_before: int, tokens_after: int) -> None:
        con = self._conn()
        con.execute(
            "INSERT INTO compaction_log (session_id, original_count, compacted_count, tokens_before, tokens_after) VALUES (?,?,?,?,?)",
            (session_id, original_count, compacted_count, tokens_before, tokens_after),
        )
        con.commit()
        con.close()

    def _sync_get_usage_stats(self, session_id: str | None = None) -> dict:
        con = self._conn()
        where = "session_id = ?" if session_id else "1=1"
        params = (session_id,) if session_id else ()
        row = con.execute(
            f"SELECT COALESCE(SUM(input_tokens),0) as input, COALESCE(SUM(output_tokens),0) as output, "
            f"COALESCE(SUM(cost_usd),0) as cost, COUNT(*) as count FROM token_usage WHERE {where}",
            params,
        ).fetchone()
        con.close()
        return {"input_tokens": row["input"], "output_tokens": row["output"],
                "cost_usd": round(row["cost"], 6), "request_count": row["count"]}

    # ── Async public API (offloaded to thread pool) ──────────────────

    async def create_session(self, session_id: str, title: str, provider: str, model: str) -> None:
        await self._run(self._sync_create_session, session_id, title, provider, model)

    async def get_session(self, session_id: str) -> dict | None:
        return await self._run(self._sync_get_session, session_id)

    async def list_sessions(self) -> list[dict]:
        return await self._run(self._sync_list_sessions)

    async def update_session(self, session_id: str, **fields: Any) -> None:
        await self._run(partial(self._sync_update_session, session_id, **fields))

    async def delete_session(self, session_id: str) -> None:
        await self._run(self._sync_delete_session, session_id)

    async def add_message(self, session_id: str, message: Message) -> None:
        await self._run(self._sync_add_message, session_id, message)

    async def get_messages(self, session_id: str) -> list[Message]:
        return await self._run(self._sync_get_messages, session_id)

    async def replace_messages(self, session_id: str, messages: list[Message]) -> None:
        await self._run(self._sync_replace_messages, session_id, messages)

    async def log_usage(self, session_id: str, model: str, input_tokens: int, output_tokens: int, cost_usd: float) -> None:
        await self._run(self._sync_log_usage, session_id, model, input_tokens, output_tokens, cost_usd)

    async def log_compaction(self, session_id: str, original_count: int, compacted_count: int,
                             tokens_before: int, tokens_after: int) -> None:
        await self._run(self._sync_log_compaction, session_id, original_count, compacted_count, tokens_before, tokens_after)

    async def get_usage_stats(self, session_id: str | None = None) -> dict:
        return await self._run(self._sync_get_usage_stats, session_id)
