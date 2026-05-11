"""Provider configurations — models, context windows, costs."""
from __future__ import annotations

from ..core.types import ModelInfo, ProviderType

# ── Context window sizes ─────────────────────────────────────────────

CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI
    "gpt-4.1": 1_000_000,
    "gpt-4.1-mini": 1_000_000,
    "gpt-4.1-nano": 1_000_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-3.5-turbo": 16_384,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3": 200_000,
    "o3-mini": 200_000,
    "o4-mini": 200_000,
    "gpt-5-mini": 1_000_000,
    "gpt-5.4": 1_000_000,
    # Claude
    "claude-opus-4-20250514": 200_000,
    "claude-sonnet-4-20250514": 200_000,
    "claude-haiku-3-5-20241022": 200_000,
    "claude-sonnet-4.5": 200_000,
    "claude-opus-4.6": 200_000,
    "haiku": 200_000,
    "sonnet": 200_000,
    "opus": 200_000,
    # Copilot models (same as OpenAI + Claude names)
    "claude-3.5-sonnet": 200_000,
    "claude-sonnet-4": 200_000,
    # Local / vLLM
    "qwen3-27b": 250_000,
    "/home/ng6355/models/qwen3-6-27b": 250_000,
}

# ── Cost per 1M tokens (input, output) ───────────────────────────────

COST_TABLE: dict[str, tuple[float, float]] = {
    "gpt-4.1": (2.0, 8.0),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4o": (2.50, 10.0),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-5-mini": (0.40, 1.60),
    "gpt-5.4": (2.0, 8.0),
    "o1": (15.0, 60.0),
    "o3": (10.0, 40.0),
    "o3-mini": (1.10, 4.40),
    "o4-mini": (1.10, 4.40),
    "claude-haiku-3-5-20241022": (0.80, 4.0),
    "haiku": (0.80, 4.0),
    "claude-sonnet-4-20250514": (3.0, 15.0),
    "sonnet": (3.0, 15.0),
    "claude-sonnet-4.5": (3.0, 15.0),
    "claude-opus-4-20250514": (15.0, 75.0),
    "claude-opus-4.6": (15.0, 75.0),
    "opus": (15.0, 75.0),
    "qwen3-27b": (0.0, 0.0),
}

DEFAULT_CONTEXT_WINDOW = 128_000


def get_context_window(model: str) -> int:
    if model in CONTEXT_WINDOWS:
        return CONTEXT_WINDOWS[model]
    # Fuzzy match: check if any key is a substring
    model_lower = model.lower()
    for key, val in CONTEXT_WINDOWS.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return val
    return DEFAULT_CONTEXT_WINDOW


def get_cost(model: str) -> tuple[float, float]:
    if model in COST_TABLE:
        return COST_TABLE[model]
    model_lower = model.lower()
    for key, val in COST_TABLE.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return val
    return (0.0, 0.0)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    ic, oc = get_cost(model)
    return (input_tokens * ic + output_tokens * oc) / 1_000_000


# ── Default models per provider ──────────────────────────────────────

DEFAULT_MODELS: dict[ProviderType, str] = {
    ProviderType.OPENAI: "gpt-4.1",
    ProviderType.COPILOT: "gpt-4.1",
    ProviderType.CLAUDE: "haiku",
}
