# Agent Scaling

Long-running autonomous task execution via SQLite todo lists. Agent wakes up, works a batch, sleeps. Repeat until done.

## Concept

```
create_task(goal, todos)
      ↓
  agent.db  ←─────────────────────────────┐
      ↓                                    │
run_session()                              │
  ├── pick N pending todos (atomic)        │
  ├── inject <state> into agent prompt     │
  ├── agent works batch, calls tools       │
  ├── mark_done / mark_failed per todo     │
  └── session ends → call again ───────────┘
```

Todo status flow: `pending → picked → done | failed`

Crashed sessions auto-recover: stale `picked` todos reset to `pending` on next `session_start`.

## Files

| File | Purpose |
|---|---|
| `db.py` | SQLite layer — tasks, todos, sessions, messages |
| `agent.py` | Agent runner — session loop, mark_done/mark_failed tools |
| `schema.sql` | DB schema reference |
| `test_run.py` | Quick smoke test — 5 web search todos |
| `agent.db` | SQLite state file (gitignored) |

## Usage

```python
from kivi_ai.scaling import create_task, run_session

task_id = create_task(
    goal="Search each query and summarize.",
    todos=["Search: vLLM benchmarks 2025", "Search: Qwen3 architecture"],
    max_parallel=4,
)

# call run_session() in a loop or via cron until all done
while True:
    state = run_session(task_id, verbose=True)
    if state["all_done"]:
        break
```

## Agent Tools

Each session gets:

- `bash`, `read`, `write`, `edit`, `glob`, `grep` — filesystem/shell
- `web_search` — DuckDuckGo search (via `duckduckgo-search`)
- `web_fetch` — fetch URL → Markdown → ChromaDB
- `run_markdown_agent` — query a fetched doc by `doc_id`
- `mark_done(todo_id, result)` — mark todo complete
- `mark_failed(todo_id, error)` — mark todo failed

## State Injection

Every session the agent sees a fresh `<state>` block:

```
<state>
goal: ...
progress: 3/10 done, 7 pending
your batch:
  todo_id=4: Search: vLLM benchmarks 2025
  todo_id=5: Search: Qwen3 architecture
</state>
```

Agent never hallucinates progress — always reads from DB.

## DB Schema

```
tasks    — goal, soul, status, max_parallel
todos    — task_id, description, status, result, error, session_id
sessions — task_id, status, todos_picked, started_at, ended_at
messages — session_id, role, content, token_count
```

## Provider

Default: GPU4 vLLM at `http://192.168.170.49:8077/v1` (Qwen3-6-27B).
Override via `OPENAI_BASE_URL` env var or pass `base_url` to `OpenAIProvider`.
