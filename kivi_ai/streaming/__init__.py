"""Streaming package — adapter and SSE formatter."""
from .adapter import normalize_stream
from .sse import stream_to_sse

__all__ = ["normalize_stream", "stream_to_sse"]
