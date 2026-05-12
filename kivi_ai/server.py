"""Unified AI Chat Server — FastAPI routing layer."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, FileResponse
from starlette.middleware.cors import CORSMiddleware

from .core.registry import Registry
from .core.types import ChunkType, Message, ProviderType, Role, StreamChunk, ToolCall, ToolResult
from .providers.config import DEFAULT_MODELS, estimate_cost
from .sessions.compaction import check_and_compact
from .sessions.manager import SessionManager
from .sessions.store import SQLiteSessionStore
from .streaming.adapter import normalize_stream
from .streaming.sse import stream_to_sse
from .tools.builtins import register_builtin_tools

VLLM_URL = os.environ.get("VLLM_URL", "http://192.168.170.49:8077")
WORK_DIR = os.path.expanduser("~")

app = FastAPI(title="Unified AI Chat")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── Globals ──────────────────────────────────────────────────────────
_session_manager: SessionManager | None = None


def _mgr() -> SessionManager:
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager


# ── Lifecycle ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    register_builtin_tools()
    _register_providers()
    await Registry.initialize_all()


@app.on_event("shutdown")
async def shutdown():
    await Registry.shutdown_all()


def _register_providers():
    from .providers.openai_provider import OpenAIProvider
    from .providers.copilot_provider import CopilotProvider
    from .providers.claude_provider import ClaudeProvider

    # OpenAI (direct API)
    Registry.register_provider("openai", OpenAIProvider(
        api_key=os.environ.get("OPENAI_API_KEY", ""),
    ))

    VLLM_MODEL = os.environ.get("VLLM_MODEL", "default")

    # vLLM (OpenAI-compatible local)
    Registry.register_provider("vllm", OpenAIProvider(
        api_key="sk-xxx",
        base_url=f"{VLLM_URL}/v1",
        default_model=VLLM_MODEL,
        provider_label="vllm",
    ))

    # GitHub Copilot
    Registry.register_provider("copilot", CopilotProvider())

    # Copilot + vLLM backend
    Registry.register_provider("qwen-copilot", CopilotProvider(vllm_url=VLLM_URL))

    # Claude (Anthropic)
    Registry.register_provider("claude", ClaudeProvider())

    # Claude + vLLM backend
    Registry.register_provider("qwen-claude", ClaudeProvider(vllm_url=VLLM_URL))


# ── Unified Chat Streaming ──────────────────────────────────────────

@app.post("/api/chat/stream")
async def chat_stream(request: Request):
    """Unified streaming endpoint for all providers.

    Body: {
        session_id: str (optional — creates new if missing),
        provider: "openai"|"vllm"|"copilot"|"qwen-copilot"|"claude"|"qwen-claude",
        model: str (optional),
        messages: [{role, content}] (current conversation),
        system_prompt: str (optional),
        temperature: float (optional),
    }
    """
    data = await request.json()
    provider_name = data.get("provider", "openai")
    model = data.get("model", "")
    session_id = data.get("session_id")
    raw_messages = data.get("messages", [])
    system_prompt = data.get("system_prompt")
    temperature = data.get("temperature")

    try:
        provider = Registry.get_provider(provider_name)
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if not model:
        # Map compound provider names to their base ProviderType for default model lookup
        _provider_type_map = {
            "openai": ProviderType.OPENAI, "vllm": ProviderType.OPENAI,
            "copilot": ProviderType.COPILOT, "qwen-copilot": ProviderType.COPILOT,
            "claude": ProviderType.CLAUDE, "qwen-claude": ProviderType.CLAUDE,
        }
        base_type = _provider_type_map.get(provider_name, ProviderType.OPENAI)
        model = DEFAULT_MODELS.get(base_type, "gpt-4.1")

    mgr = _mgr()

    # Create or load session
    if not session_id:
        title = "Untitled"
        if raw_messages:
            for m in raw_messages:
                if m.get("role") == "user":
                    title = SessionManager.generate_title(m.get("content", ""))
                    break
        session_id = await mgr.create_session(provider=provider_name, model=model, title=title)
    else:
        session = await mgr.get_session(session_id)
        if not session:
            session_id = await mgr.create_session(provider=provider_name, model=model, title="Untitled")

    # Convert raw messages to Message objects and store the new user message
    messages = [Message.from_dict(m) for m in raw_messages]

    # Store the latest user message
    if messages and messages[-1].role == Role.USER:
        await mgr.add_message(session_id, messages[-1])

    # Update session provider/model if changed
    await mgr.update_session(session_id, provider=provider_name, model=model)

    # Check compaction before streaming
    use_vllm = provider_name.startswith("qwen-")

    # Check if tools should be enabled (frontend sends enable_tools flag or mode implies it)
    enable_tools = data.get("enable_tools", True)  # default on — let the model decide
    tool_schemas = None
    if enable_tools and provider.supports_tools:
        tools_list = Registry.list_tools()
        if tools_list:
            tool_schemas = [t.schema for t in tools_list]

    async def generate():
        # Compaction check
        compaction_chunk = await check_and_compact(session_id, mgr, provider, model)
        if compaction_chunk:
            yield f"data: {json.dumps(compaction_chunk.to_sse_dict())}\n\n"
            # Reload messages after compaction
            stored = await mgr.get_messages(session_id)
            messages_to_send = stored
        else:
            messages_to_send = messages

        # Emit session_id for the frontend
        yield f"data: {json.dumps({'type': 'session', 'session_id': session_id})}\n\n"

        # Tool execution loop — keeps going until model produces text (no tool calls)
        MAX_TOOL_ROUNDS = 10
        current_messages = list(messages_to_send)
        full_content = ""
        full_thinking = ""
        stream_meta: dict[str, Any] = {}

        for tool_round in range(MAX_TOOL_ROUNDS):
            round_content = ""
            round_thinking = ""
            round_tool_calls: list[dict] = []

            try:
                raw_stream = provider.stream(
                    current_messages, model,
                    tools=tool_schemas,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    use_vllm=use_vllm,
                )
                async for chunk in normalize_stream(raw_stream):
                    if chunk.type == ChunkType.DELTA:
                        round_content += chunk.content
                    elif chunk.type == ChunkType.THINKING_DELTA:
                        round_thinking += chunk.content
                    elif chunk.type == ChunkType.DONE:
                        stream_meta = chunk.metadata
                        round_tool_calls = stream_meta.get("tool_calls", [])
                    yield f"data: {json.dumps(chunk.to_sse_dict())}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
                yield "data: [DONE]\n\n"
                return

            full_content += round_content
            full_thinking += round_thinking

            # If no tool calls, we're done
            if not round_tool_calls:
                break

            # Execute each tool call
            # First, add assistant message with tool calls to context
            assistant_tc_msg = Message(
                role=Role.ASSISTANT,
                content=round_content,
                tool_calls=[
                    ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                    for tc in round_tool_calls
                ],
            )
            current_messages.append(assistant_tc_msg)

            tool_results_for_msg: list[ToolResult] = []
            for tc in round_tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                tool_call_id = tc["id"]

                # Execute the tool
                try:
                    tool_impl = Registry.get_tool(tool_name)
                    result = await tool_impl.execute(tool_args, work_dir=WORK_DIR)

                    # Emit tool_complete event
                    yield f"data: {json.dumps({'type': 'tool_complete', 'tool_call_id': tool_call_id, 'name': tool_name, 'result': result.output, 'is_error': result.is_error})}\n\n"

                    tool_results_for_msg.append(ToolResult(
                        tool_call_id=tool_call_id,
                        content=result.output,
                        is_error=result.is_error,
                    ))
                except Exception as e:
                    error_msg = f"Tool '{tool_name}' failed: {str(e)}"
                    yield f"data: {json.dumps({'type': 'tool_complete', 'tool_call_id': tool_call_id, 'name': tool_name, 'result': error_msg, 'is_error': True})}\n\n"
                    tool_results_for_msg.append(ToolResult(
                        tool_call_id=tool_call_id,
                        content=error_msg,
                        is_error=True,
                    ))

            # Add tool results as a message for next round
            current_messages.append(Message(
                role=Role.TOOL,
                content="",
                tool_results=tool_results_for_msg,
            ))

        # Store assistant response
        if full_content or full_thinking:
            assistant_msg = Message(
                role=Role.ASSISTANT,
                content=full_content,
                thinking=full_thinking or None,
                metadata={"model": model, "provider": provider_name},
            )
            await mgr.add_message(session_id, assistant_msg)

        # Log token usage
        input_tokens = stream_meta.get("input_tokens", 0)
        output_tokens = stream_meta.get("output_tokens", 0)
        if not input_tokens:
            input_tokens = provider.count_tokens(" ".join(m.content for m in messages), model)
        if not output_tokens:
            output_tokens = provider.count_tokens(full_content, model)
        cost = stream_meta.get("cost_usd", estimate_cost(model, input_tokens, output_tokens))
        await mgr.log_usage(session_id, model, input_tokens, output_tokens, cost)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Session API ──────────────────────────────────────────────────────

@app.get("/api/sessions")
async def list_sessions():
    return JSONResponse(await _mgr().list_sessions())


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str):
    s = await _mgr().get_session(session_id)
    if not s:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse(s)


@app.post("/api/sessions")
async def create_session(request: Request):
    data = await request.json()
    sid = await _mgr().create_session(
        provider=data.get("provider", "openai"),
        model=data.get("model", ""),
        title=data.get("title", "Untitled"),
    )
    return JSONResponse({"id": sid})


@app.put("/api/sessions/{session_id}")
async def update_session(session_id: str, request: Request):
    data = await request.json()
    await _mgr().update_session(session_id, **data)
    return JSONResponse({"ok": True})


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    await _mgr().delete_session(session_id)
    return JSONResponse({"ok": True})


@app.get("/api/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    msgs = await _mgr().get_messages(session_id)
    return JSONResponse([m.to_dict() for m in msgs])


# ── Provider switching ───────────────────────────────────────────────

@app.post("/api/sessions/{session_id}/switch")
async def switch_provider(session_id: str, request: Request):
    data = await request.json()
    provider = data.get("provider", "openai")
    model = data.get("model", "")
    await _mgr().switch_provider(session_id, provider, model)
    return JSONResponse({"ok": True, "provider": provider, "model": model})


# ── Provider & model discovery ───────────────────────────────────────

@app.get("/api/providers")
async def list_providers():
    providers = []
    for name in Registry.list_providers():
        p = Registry.get_provider(name)
        providers.append({
            "name": name,
            "supports_streaming": p.supports_streaming,
            "supports_tools": p.supports_tools,
            "supports_thinking": p.supports_thinking,
        })
    return JSONResponse(providers)


@app.get("/api/models/{provider_name}")
async def list_models(provider_name: str):
    try:
        provider = Registry.get_provider(provider_name)
        models = await provider.list_models()
        return JSONResponse([m.to_dict() for m in models])
    except KeyError as e:
        return JSONResponse({"error": str(e)}, status_code=404)


# ── Tool listing ─────────────────────────────────────────────────────

@app.get("/api/tools")
async def list_tools():
    tools = Registry.list_tools()
    return JSONResponse([t.schema.to_openai_schema() for t in tools])


# ── Usage stats ──────────────────────────────────────────────────────

@app.get("/api/usage")
async def usage_stats():
    return JSONResponse(await _mgr().store.get_usage_stats())


@app.get("/api/usage/{session_id}")
async def session_usage(session_id: str):
    return JSONResponse(await _mgr().store.get_usage_stats(session_id))


# ── File utilities (carried over from old server) ────────────────────

@app.get("/api/files")
async def search_files(q: str = "", cwd: str = "", limit: int = 5):
    search_dir = cwd or os.path.expanduser("~")
    if not os.path.isdir(search_dir):
        search_dir = os.path.expanduser("~")
    try:
        proc = await asyncio.create_subprocess_exec(
            "rg", "--files",
            "--glob", "!node_modules", "--glob", "!__pycache__",
            "--glob", "!*.pyc", "--glob", "!.*/",
            search_dir,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        files = stdout.decode().strip().splitlines()
        if q:
            q_lower = q.lower()
            scored = []
            for f in files:
                fname = os.path.basename(f).lower()
                if q_lower in fname:
                    scored.append((0, f))
                elif q_lower in f.lower():
                    scored.append((1, f))
            scored.sort(key=lambda x: (x[0], len(x[1])))
            return JSONResponse([s[1] for s in scored[:limit]])
        return JSONResponse(files[:limit])
    except Exception:
        return JSONResponse([])


@app.get("/api/file-preview")
async def file_preview(path: str):
    path = os.path.expanduser(path)
    resolved = os.path.realpath(path)
    # Sandbox: only serve files under user's home directory
    home = os.path.expanduser("~")
    if not resolved.startswith(home):
        return JSONResponse({"error": "Access denied: path outside home directory"}, status_code=403)
    if not os.path.isfile(resolved):
        return JSONResponse({"error": "File not found"}, status_code=404)
    ext = os.path.splitext(path)[1].lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".svg": "image/svg+xml",
        ".mp4": "video/mp4", ".webm": "video/webm",
        ".txt": "text/plain", ".md": "text/markdown",
        ".json": "application/json", ".csv": "text/csv",
        ".py": "text/plain", ".js": "text/plain", ".html": "text/html",
        ".pdf": "application/pdf",
    }
    mime = mime_map.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=mime)


# ── Git endpoints (carried over) ─────────────────────────────────────

@app.get("/api/git/diff")
async def git_diff(path: str):
    if not os.path.isdir(path):
        return JSONResponse({"error": "Not a directory"}, status_code=400)

    async def run(cmd):
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=path
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode().strip(), err.decode().strip()

    rc, _, _ = await run(["git", "rev-parse", "--is-inside-work-tree"])
    if rc != 0:
        return JSONResponse({"error": "Not a git repo"}, status_code=400)

    _, branch, _ = await run(["git", "branch", "--show-current"])
    _, status, _ = await run(["git", "status", "--short"])
    _, staged, _ = await run(["git", "diff", "--cached"])
    _, unstaged, _ = await run(["git", "diff"])
    _, log_out, _ = await run(["git", "log", "-10", "--format=%H|%h|%s|%an|%ai"])

    commits = []
    for line in log_out.splitlines():
        parts = line.split("|", 4)
        if len(parts) >= 5:
            commits.append({"sha": parts[0], "short": parts[1], "msg": parts[2], "author": parts[3], "date": parts[4]})

    return JSONResponse({
        "branch": branch, "status": status, "staged": staged,
        "unstaged": unstaged, "commits": commits,
        "has_changes": bool(status.strip()),
    })


@app.post("/api/git/commit")
async def git_commit(request: Request):
    data = await request.json()
    path, message = data.get("path", ""), data.get("message", "")
    if not path or not message:
        return JSONResponse({"error": "path and message required"}, status_code=400)

    async def run(cmd):
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=path
        )
        out, err = await proc.communicate()
        return proc.returncode, out.decode().strip(), err.decode().strip()

    stage = data.get("files")
    if stage:
        for f in stage:
            await run(["git", "add", f])
    else:
        await run(["git", "add", "-A"])
    rc, out, err = await run(["git", "commit", "-m", message])
    return JSONResponse({"success": rc == 0, "output": out or err})


@app.post("/api/git/push")
async def git_push(request: Request):
    data = await request.json()
    path = data.get("path", "")
    proc = await asyncio.create_subprocess_exec(
        "git", "push", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=path
    )
    out, err = await proc.communicate()
    return JSONResponse({"success": proc.returncode == 0, "output": (out or err or b"").decode().strip()})


# ── Serve frontend ───────────────────────────────────────────────────

@app.get("/")
async def serve_index():
    html_path = Path(__file__).parent / "frontend" / "index.html"
    if not html_path.exists():
        return HTMLResponse("<h1>Unified AI Chat</h1><p>Frontend not built yet.</p>")
    return HTMLResponse(html_path.read_text())


# ── Entry point ──────────────────────────────────────────────────────

def main():
    print("Unified AI Chat → http://localhost:8899")
    uvicorn.run(app, host="0.0.0.0", port=8899, log_level="info")


if __name__ == "__main__":
    main()
