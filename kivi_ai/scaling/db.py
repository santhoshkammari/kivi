import sqlite3
import json
from pathlib import Path
from datetime import datetime
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "agent.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    goal         TEXT NOT NULL,
    soul         TEXT NOT NULL,
    status       TEXT DEFAULT 'active',
    max_parallel INTEGER DEFAULT 4,
    created_at   TEXT DEFAULT (datetime('now')),
    done_at      TEXT
);

CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id),
    description TEXT NOT NULL,
    status      TEXT DEFAULT 'pending',
    result      TEXT,
    error       TEXT,
    session_id  INTEGER,
    picked_at   TEXT,
    done_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_todos_task_status ON todos(task_id, status);

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id      INTEGER NOT NULL,
    status       TEXT DEFAULT 'running',
    todos_picked TEXT,
    started_at   TEXT DEFAULT (datetime('now')),
    ended_at     TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    token_count INTEGER,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
"""


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with conn() as c:
        c.executescript(SCHEMA)


# ── tasks ──────────────────────────────────────────────────────────────────

def create_task(goal: str, soul: str, max_parallel: int = 4) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO tasks (goal, soul, max_parallel) VALUES (?,?,?)",
            (goal, soul, max_parallel)
        )
        return cur.lastrowid


def get_task(task_id: int) -> dict:
    with conn() as c:
        row = c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None


def mark_task_done(task_id: int):
    with conn() as c:
        c.execute(
            "UPDATE tasks SET status='done', done_at=datetime('now') WHERE id=?",
            (task_id,)
        )


# ── todos ──────────────────────────────────────────────────────────────────

def create_todos(task_id: int, descriptions: list[str]) -> list[int]:
    with conn() as c:
        ids = []
        for desc in descriptions:
            cur = c.execute(
                "INSERT INTO todos (task_id, description) VALUES (?,?)",
                (task_id, desc)
            )
            ids.append(cur.lastrowid)
        return ids


def pick_todos(session_id: int, task_id: int, n: int) -> list[dict]:
    """Atomically pick up to n pending todos, mark them as picked."""
    with conn() as c:
        rows = c.execute(
            """SELECT id FROM todos
               WHERE task_id=? AND status='pending'
               ORDER BY id LIMIT ?""",
            (task_id, n)
        ).fetchall()

        if not rows:
            return []

        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        c.execute(
            f"""UPDATE todos
                SET status='picked', session_id=?, picked_at=datetime('now')
                WHERE id IN ({placeholders})""",
            [session_id, *ids]
        )

        rows = c.execute(
            f"SELECT * FROM todos WHERE id IN ({placeholders})", ids
        ).fetchall()
        return [dict(r) for r in rows]


def mark_todo_done(todo_id: int, result: dict | str):
    with conn() as c:
        c.execute(
            """UPDATE todos
               SET status='done', result=?, done_at=datetime('now')
               WHERE id=?""",
            (json.dumps(result) if isinstance(result, dict) else result, todo_id)
        )


def mark_todo_failed(todo_id: int, error: str):
    with conn() as c:
        c.execute(
            """UPDATE todos
               SET status='failed', error=?, done_at=datetime('now')
               WHERE id=?""",
            (error, todo_id)
        )


def get_todos(task_id: int, status: str = None) -> list[dict]:
    with conn() as c:
        if status:
            rows = c.execute(
                "SELECT * FROM todos WHERE task_id=? AND status=? ORDER BY id",
                (task_id, status)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM todos WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]


# ── sessions ───────────────────────────────────────────────────────────────

def session_start(task_id: int) -> int:
    """Reset crashed/stale sessions, create new session, return session_id."""
    with conn() as c:
        # find all non-done sessions for this task
        stale = c.execute(
            """SELECT id FROM sessions
               WHERE task_id=? AND status IN ('running', 'crashed')""",
            (task_id,)
        ).fetchall()

        stale_ids = [r["id"] for r in stale]

        if stale_ids:
            placeholders = ",".join("?" * len(stale_ids))
            # mark them crashed
            c.execute(
                f"UPDATE sessions SET status='crashed' WHERE id IN ({placeholders})",
                stale_ids
            )
            # reset their picked todos back to pending
            c.execute(
                f"""UPDATE todos
                    SET status='pending', session_id=NULL, picked_at=NULL
                    WHERE status='picked' AND session_id IN ({placeholders})""",
                stale_ids
            )

        cur = c.execute(
            "INSERT INTO sessions (task_id) VALUES (?)", (task_id,)
        )
        return cur.lastrowid


def session_end(session_id: int, todo_ids: list[int]):
    with conn() as c:
        # reset any todos still picked (not marked done/failed) back to pending
        c.execute(
            """UPDATE todos
               SET status='pending', session_id=NULL, picked_at=NULL
               WHERE session_id=? AND status='picked'""",
            (session_id,)
        )
        c.execute(
            """UPDATE sessions
               SET status='done', todos_picked=?, ended_at=datetime('now')
               WHERE id=?""",
            (json.dumps(todo_ids), session_id)
        )


def session_crash(session_id: int):
    with conn() as c:
        c.execute(
            "UPDATE sessions SET status='crashed', ended_at=datetime('now') WHERE id=?",
            (session_id,)
        )


# ── messages ───────────────────────────────────────────────────────────────

def save_message(session_id: int, role: str, content: str, token_count: int = None):
    with conn() as c:
        c.execute(
            "INSERT INTO messages (session_id, role, content, token_count) VALUES (?,?,?,?)",
            (session_id, role, content, token_count)
        )


def get_messages(session_id: int) -> list[dict]:
    with conn() as c:
        rows = c.execute(
            "SELECT * FROM messages WHERE session_id=? ORDER BY id",
            (session_id,)
        ).fetchall()
        return [dict(r) for r in rows]


# ── state (for state-role injection) ───────────────────────────────────────

def get_state(task_id: int) -> dict:
    with conn() as c:
        task = dict(c.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

        counts = dict(c.execute(
            """SELECT status, count(*) as n FROM todos
               WHERE task_id=? GROUP BY status""",
            (task_id,)
        ).fetchall() or [])

        total = sum(counts.values())
        done = counts.get("done", 0)
        failed = counts.get("failed", 0)
        pending = counts.get("pending", 0)

        last_session = c.execute(
            """SELECT * FROM sessions WHERE task_id=? AND status='done'
               ORDER BY ended_at DESC LIMIT 1""",
            (task_id,)
        ).fetchone()

        return {
            "task_id": task_id,
            "goal": task["goal"],
            "progress": f"{done}/{total}",
            "done": done,
            "failed": failed,
            "pending": pending,
            "total": total,
            "max_parallel": task["max_parallel"],
            "last_session": dict(last_session) if last_session else None,
            "all_done": pending == 0 and done + failed == total,
        }
