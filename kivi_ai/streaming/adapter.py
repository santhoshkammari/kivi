"""Stream normalization adapter."""
from __future__ import annotations

from typing import AsyncIterator

from ..core.types import ChunkType, StreamChunk


async def normalize_stream(raw: AsyncIterator[StreamChunk]) -> AsyncIterator[StreamChunk]:
    """Pass-through normalizer that filters empty deltas and ensures a DONE at end."""
    got_done = False
    try:
        async for chunk in raw:
            # Skip empty deltas
            if chunk.type in (ChunkType.DELTA, ChunkType.THINKING_DELTA) and not chunk.content:
                continue
            if chunk.type == ChunkType.DONE:
                got_done = True
            yield chunk
    except Exception as e:
        yield StreamChunk(type=ChunkType.ERROR, content=str(e))
    finally:
        if not got_done:
            yield StreamChunk(type=ChunkType.DONE)
