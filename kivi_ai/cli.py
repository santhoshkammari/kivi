"""Kivi CLI — unified AI chat server."""
import sys
import os
import argparse


HELP_TEXT = """
Kivi — Unified AI Chat Interface
Provider-agnostic chat with streaming, tools, sessions & auto-compaction

Usage:
  kivi                    Start the server (default port 8899)
  kivi --port 9000        Start on custom port
  kivi --host 0.0.0.0     Bind to all interfaces
  kivi --vllm-url URL     Set vLLM backend URL
  kivi --help             Show this help

Providers:
  chat / kivi             Local vLLM (Qwen3-27B)
  copilot                 GitHub Copilot SDK
  qwen-copilot            Copilot SDK + vLLM backend
  claude                  Claude Agent SDK (Anthropic)
  qwen-claude             Claude SDK + vLLM backend

Environment Variables:
  VLLM_URL                vLLM server URL (default: http://192.168.170.49:8077)
  OPENAI_API_KEY          OpenAI API key (for direct OpenAI provider)
  KIVI_PORT               Default port (default: 8899)
  KIVI_HOST               Default host (default: 0.0.0.0)
"""


def run():
    """kivi — start the unified AI chat server."""
    parser = argparse.ArgumentParser(
        prog="kivi",
        description="Kivi — Unified AI Chat Interface",
        add_help=True,
    )
    parser.add_argument("--port", "-p", type=int,
                        default=int(os.environ.get("KIVI_PORT", "8899")),
                        help="Port to listen on (default: 8899)")
    parser.add_argument("--host", "-H", type=str,
                        default=os.environ.get("KIVI_HOST", "0.0.0.0"),
                        help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--vllm-url", type=str, default=None,
                        help="vLLM server URL (overrides VLLM_URL env)")
    parser.add_argument("--reload", action="store_true",
                        help="Enable auto-reload for development")

    args = parser.parse_args()

    if args.vllm_url:
        os.environ["VLLM_URL"] = args.vllm_url

    import uvicorn
    uvicorn.run(
        "kivi_ai.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    run()
