# 🥝 Kivi — Unified AI Chat Interface

[![PyPI](https://img.shields.io/pypi/v/kivi-ai)](https://pypi.org/project/kivi-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)

Provider-agnostic AI chat with **token-level streaming**, **server-side tools**, **session persistence**, and **auto-compaction**. One beautiful UI, any backend.

<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-10a37f?logo=openai" />
  <img src="https://img.shields.io/badge/vLLM-supported-7aaeE0" />
  <img src="https://img.shields.io/badge/Copilot_SDK-supported-3fb950?logo=github" />
  <img src="https://img.shields.io/badge/Claude_SDK-supported-c49cde" />
</p>

## ✨ Features

- **🔀 Provider Switching** — Switch between OpenAI, vLLM, Copilot, Claude mid-conversation
- **⚡ Token-Level Streaming** — Real-time token streaming for all providers (not word-level)
- **🛠️ Server-Side Tools** — bash, read, write, edit, glob, grep, web_search, web_fetch
- **💾 Session Persistence** — SQLite-backed sessions with full message history
- **📦 Auto-Compaction** — Automatically compacts context at 75% of provider's window
- **🎨 Claude-like UI** — Dark/light themes, thinking blocks, tool blocks, markdown, code highlighting, LaTeX, SVG preview
- **📊 Token Dashboard** — Usage tracking with Plotly charts
- **🔧 Git Dashboard** — Built-in diff viewer, commit & push

## 🚀 Quick Start

```bash
pip install kivi-ai
kivi
```

Open **http://localhost:8899** in your browser. That's it.

## 📦 Install with SDK support

```bash
# With GitHub Copilot SDK support
pip install kivi-ai[copilot]

# With Claude Agent SDK support
pip install kivi-ai[claude]

# Everything
pip install kivi-ai[all]
```

## ⚙️ Configuration

All configuration via environment variables or CLI flags:

```bash
# Set vLLM backend URL
kivi --vllm-url http://your-server:8000

# Custom port
kivi --port 9000

# Or use environment variables
export VLLM_URL=http://your-server:8000
export OPENAI_API_KEY=sk-...
export KIVI_PORT=9000
kivi
```

### CLI Options

```
kivi                    Start server (default: 0.0.0.0:8899)
kivi --port 9000        Custom port
kivi --host 127.0.0.1   Bind to localhost only
kivi --vllm-url URL     vLLM backend URL
kivi --reload           Dev mode with auto-reload
kivi --help             Show help
```

## 🏗️ Architecture

```
kivi_ai/
├── core/               # Types, interfaces, registry
│   ├── types.py        # Message, StreamChunk, ToolCall, ModelInfo, etc.
│   ├── interfaces.py   # BaseProvider ABC, ToolInterface, SessionStore
│   └── registry.py     # Provider & tool registry singleton
├── providers/          # Provider implementations
│   ├── openai_provider.py   # OpenAI & vLLM (OpenAI-compatible)
│   ├── copilot_provider.py  # GitHub Copilot SDK
│   ├── claude_provider.py   # Claude Agent SDK
│   └── config.py            # Context windows, costs, defaults
├── streaming/          # Stream processing
│   ├── adapter.py      # Normalize streams (filter empty, ensure DONE)
│   └── sse.py          # StreamChunk → SSE text
├── sessions/           # Session management
│   ├── store.py        # SQLite store (async, WAL mode)
│   ├── manager.py      # Session lifecycle & provider switching
│   └── compaction.py   # Auto-compact at 75% context window
├── tools/              # Server-side tool system
│   └── builtins.py     # bash, read, write, edit, glob, grep, web_search, web_fetch
├── frontend/
│   └── index.html      # Claude-like chat UI (single file)
├── server.py           # FastAPI app — unified streaming endpoint
└── cli.py              # CLI entry point
```

### Key Design Decisions

- **All providers normalize to `AsyncIterator[StreamChunk]`** — single streaming format
- **Sessions are provider-agnostic** — switch providers without losing history
- **SQLite with WAL mode + ThreadPoolExecutor** — non-blocking async I/O
- **Atomic message sequencing** — no race conditions on concurrent writes
- **Single unified endpoint** — `POST /api/chat/stream` handles all providers

## 🔌 Providers

| Provider | Streaming | Tools | Thinking | Backend |
|----------|-----------|-------|----------|---------|
| `vllm` | ✅ Token | ✅ | ✅ | Local vLLM server |
| `openai` | ✅ Token | ✅ | ❌ | OpenAI API |
| `copilot` | ✅ Token | ✅ | ❌ | GitHub Copilot SDK |
| `claude` | ✅ Token | ✅ | ✅ | Claude Agent SDK |
| `qwen-copilot` | ✅ Token | ✅ | ❌ | Copilot SDK → vLLM |
| `qwen-claude` | ✅ Token | ✅ | ✅ | Claude SDK → vLLM |

## 🌐 API

All endpoints under the server:

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/chat/stream` | Unified streaming (SSE) |
| `GET` | `/api/sessions` | List all sessions |
| `POST` | `/api/sessions` | Create session |
| `GET` | `/api/sessions/:id/messages` | Get messages |
| `DELETE` | `/api/sessions/:id` | Delete session |
| `GET` | `/api/providers` | List providers |
| `GET` | `/api/models/:provider` | List models |
| `GET` | `/api/tools` | List available tools |
| `GET` | `/api/usage` | Token usage stats |

## 📄 License

MIT — see [LICENSE](LICENSE)
