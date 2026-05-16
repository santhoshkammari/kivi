-- ============================================================
-- agent.db — single file, all state
-- ============================================================

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    goal        TEXT NOT NULL,           -- raw user input
    soul        TEXT NOT NULL,           -- agent identity/behavior prompt
    status      TEXT DEFAULT 'active',   -- active | done | paused | failed
    max_parallel INTEGER DEFAULT 4,      -- agent-decided, capped at 4
    created_at  TEXT DEFAULT (datetime('now')),
    done_at     TEXT
);

CREATE TABLE IF NOT EXISTS todos (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL REFERENCES tasks(id),
    description TEXT NOT NULL,           -- what to do for this todo
    status      TEXT DEFAULT 'pending',  -- pending | picked | done | failed
    result      TEXT,                    -- JSON output from agent
    error       TEXT,                    -- if failed, why
    session_id  INTEGER,                 -- which session picked this
    picked_at   TEXT,
    done_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_todos_task_status ON todos(task_id, status);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    status      TEXT DEFAULT 'running',  -- running | done | crashed
    todos_picked TEXT,                   -- JSON array of todo ids this session handled
    started_at  TEXT DEFAULT (datetime('now')),
    ended_at    TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  INTEGER NOT NULL REFERENCES sessions(id),
    role        TEXT NOT NULL,           -- soul | goal | state | user | assistant | tool
    content     TEXT NOT NULL,
    token_count INTEGER,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);

-- ============================================================
-- reset picked todos from crashed sessions (run on every session start)
-- ============================================================

-- UPDATE todos
-- SET status='pending', session_id=NULL, picked_at=NULL
-- WHERE status='picked'
--   AND session_id IN (
--       SELECT id FROM sessions WHERE status='crashed' OR status='running'
--   );
