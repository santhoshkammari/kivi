# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install (editable)
uv pip install -e ".[all]"

# Run web UI server (default port 8899)
kivi serve
kivi serve --port 9000 --reload   # dev mode with auto-reload

# Run CLI agent REPL
kivi

# Single-prompt agent mode
kivi "fix the bug in main.py"
kivi --think "explain auth"        # enable thinking mode

# Build & publish
python -m build
twine upload dist/*
```

## Architecture

Kivi has **two independent subsystems** that share a name but have separate codebases:

### 1. Web UI Server (`kivi_ai/server.py` + `kivi_ai/sessions/` + `kivi_ai/providers/` + `kivi_ai/streaming/`)
FastAPI server at port 8899 serving a single-file chat UI. Key data flow:

- `POST /api/chat/stream` → `server.py:chat_stream()` — the unified streaming endpoint
- Providers are registered at startup in `_register_providers()` via `Registry` singleton
- All providers normalize output to `AsyncIterator[StreamChunk]` (see `core/types.py:StreamChunk`)
- Tool execution runs in a server-side loop (up to 250 rounds) inside the streaming generator
- Sessions are persisted to SQLite at `~/.unified-chat/sessions.db` via `SQLiteSessionStore` (WAL mode, thread pool executor for non-blocking async)
- Auto-compaction triggers at 75% of context window, replacing old messages with a summary system message (`sessions/compaction.py`)
- `~/.kivi/KIVI.md` is appended to every system prompt at runtime (editable by user for custom instructions/render tags)

### 2. CLI Agent (`kivi_ai/agent/`)
Synchronous streaming agent with tool execution, separate from the web server stack:

- `agent/agent.py:Agent.run()` — event-driven generator yielding `Event` subclasses
- Uses `agent/provider.py:OpenAIProvider` (not the same as `providers/openai_provider.py`)
- Tool calls execute in parallel via `ThreadPoolExecutor` when multiple tools are called in one round
- `agent/repl.py` handles the interactive REPL loop with auto-compaction
- Default LLM endpoint: `http://192.168.170.49:8077/v1` (local vLLM, overridable via `OPENAI_BASE_URL`)

### Provider System (Web Server)
Located in `kivi_ai/providers/`. Each provider implements `core/interfaces.py:BaseProvider` with a `stream()` method returning `AsyncIterator[StreamChunk]`.

- `openai_provider.py` — handles both OpenAI API and vLLM (OpenAI-compatible)
- `copilot_provider.py` — GitHub Copilot SDK; `qwen-copilot` variant routes to vLLM backend
- `claude_provider.py` — Claude Agent SDK; `qwen-claude` variant routes to vLLM backend
- `providers/config.py` — context window sizes, cost per token, default models per provider type

### Key Environment Variables
| Variable | Default | Purpose |
|----------|---------|---------|
| `VLLM_URL` | `http://192.168.170.49:8077` | vLLM backend for web server |
| `OPENAI_BASE_URL` | `http://192.168.170.49:8077/v1` | LLM endpoint for CLI agent |
| `OPENAI_API_KEY` | `sk-xxx` | OpenAI API key |
| `KIVI_PORT` | `8899` | Web server port |
| `KIVI_HOST` | `0.0.0.0` | Web server bind host |
| `KIVI_MAX_CONTEXT` | `250000` | Max context tokens for CLI agent |

### Packaging
Published to PyPI as `kivi-ai`. Version in `pyproject.toml`. Optional extras: `copilot`, `claude`, `all`.
