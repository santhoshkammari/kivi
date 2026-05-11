"""SSE output formatter."""
from __future__ import annotations

import json
from typing import AsyncIterator

from ..core.types import ChunkType, StreamChunk


async def stream_to_sse(chunks: AsyncIterator[StreamChunk]) -> AsyncIterator[str]:
    """Convert StreamChunk iterator to SSE text lines for the frontend."""
    async for chunk in chunks:
        if chunk.type == ChunkType.DONE:
            yield "data: [DONE]\n\n"
            return
        yield f"data: {json.dumps(chunk.to_sse_dict())}\n\n"
    # Safety: always terminate
    yield "data: [DONE]\n\n"
