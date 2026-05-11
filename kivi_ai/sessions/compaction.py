"""Auto-compaction — summarize old turns when context reaches 75% of window."""
from __future__ import annotations

import logging

from ..core.interfaces import BaseProvider
from ..core.types import ChunkType, Message, Role, StreamChunk
from .manager import SessionManager

logger = logging.getLogger(__name__)

COMPACTION_THRESHOLD = 0.75  # Trigger at 75% of context window


async def check_and_compact(
    session_id: str,
    manager: SessionManager,
    provider: BaseProvider,
    model: str,
) -> StreamChunk | None:
    """Check if session needs compaction, and do it if so.

    Returns a COMPACTION StreamChunk if compaction occurred, else None.
    """
    context_window = provider.get_context_window(model)
    threshold = int(context_window * COMPACTION_THRESHOLD)

    messages = await manager.get_messages(session_id)
    if len(messages) < 4:
        return None

    # Count total tokens
    total_tokens = 0
    for msg in messages:
        total_tokens += provider.count_tokens(msg.content, model)
        if msg.thinking:
            total_tokens += provider.count_tokens(msg.thinking, model)

    if total_tokens < threshold:
        return None

    logger.info(f"Compacting session {session_id}: {total_tokens} tokens >= {threshold} threshold")

    # Keep last 2 turns (4 messages: user+assistant pairs), summarize the rest
    keep_count = min(4, len(messages))
    old_messages = messages[:-keep_count]
    kept_messages = messages[-keep_count:]

    if not old_messages:
        return None

    # Build summary prompt from old messages
    summary_text = _build_summary(old_messages)

    # Count tokens before/after
    old_tokens = sum(provider.count_tokens(m.content, model) for m in old_messages)

    # Create summary message
    summary_msg = Message(
        role=Role.SYSTEM,
        content=f"[Conversation Summary]\n{summary_text}",
        metadata={"compacted": True, "original_count": len(old_messages)},
    )

    new_messages = [summary_msg] + kept_messages
    new_tokens = sum(provider.count_tokens(m.content, model) for m in new_messages)

    await manager.store.replace_messages(session_id, new_messages)
    await manager.store.log_compaction(
        session_id,
        original_count=len(messages),
        compacted_count=len(new_messages),
        tokens_before=total_tokens,
        tokens_after=new_tokens,
    )

    return StreamChunk(
        type=ChunkType.COMPACTION,
        content=f"Compacted {len(old_messages)} messages → summary ({old_tokens}→{new_tokens} tokens)",
        metadata={
            "original_count": len(messages),
            "new_count": len(new_messages),
            "tokens_before": total_tokens,
            "tokens_after": new_tokens,
        },
    )


def _build_summary(messages: list[Message]) -> str:
    """Build a condensed summary of messages for the compaction system message."""
    parts = []
    for msg in messages:
        prefix = msg.role.value.upper()
        content = msg.content[:500]  # Truncate long messages for summary
        if len(msg.content) > 500:
            content += "..."
        parts.append(f"[{prefix}]: {content}")
    return "\n".join(parts)
