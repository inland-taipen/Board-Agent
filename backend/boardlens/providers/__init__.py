"""Model provider selection.

`BOARDLENS_PROVIDER` picks a backend explicitly. Left at `auto` (the default),
BoardLens uses whichever credential it finds, in descending order of how well
the provider suits a board pack: Anthropic, then Gemini, then Groq.

Auto-detection exists so a pilot team can drop in whatever key they already
have and run. A production deployment should pin the provider explicitly, so
that adding an unrelated key to the environment cannot silently change which
model writes the board's briefing.
"""

from __future__ import annotations

import logging
import os
import threading

from ..config import get_settings
from .base import LLMError, Provider, strict_schema

log = logging.getLogger(__name__)

PROVIDERS = ("anthropic", "gemini", "groq")

# Ordered by suitability for a 500-page board pack, not by cost.
_AUTO_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("anthropic", ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")),
    ("gemini", ("GEMINI_API_KEY", "GOOGLE_API_KEY")),
    ("groq", ("GROQ_API_KEY",)),
)

_provider: Provider | None = None
_lock = threading.Lock()


# `.env.example` ships placeholders. Once the file is loaded into the
# environment they are non-empty strings, so a leftover `ANTHROPIC_API_KEY=sk-ant-...`
# would win auto-detection and fail every pass. Recognise the obvious ones.
_PLACEHOLDER_MARKERS = ("your-", "your_", "xxx", "changeme", "change-me", "replace")
_MIN_CREDENTIAL_LEN = 16


def is_placeholder(value: str | None) -> bool:
    """True when a value is present but is clearly not a real credential."""
    if value is None:
        return True
    value = value.strip()
    if not value:
        return True
    if value.endswith("...") or value.rstrip(".") == "":
        return True
    lowered = value.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    # Every provider's keys are far longer than this; nothing real is this short.
    return len(value) < _MIN_CREDENTIAL_LEN


def credential_for(env_keys: tuple[str, ...]) -> str | None:
    """The first usable credential among `env_keys`, ignoring placeholders."""
    for key in env_keys:
        value = os.environ.get(key)
        if value is None:
            continue
        if is_placeholder(value):
            log.warning(
                "%s is set but looks like a placeholder, so it is being ignored. "
                "Remove it or replace it with a real key.",
                key,
            )
            continue
        return value
    return None


def detect_provider() -> str | None:
    """Return the first provider with a usable credential in the environment."""
    for name, env_keys in _AUTO_ORDER:
        if credential_for(env_keys):
            return name
    return None


def resolve_provider_name() -> str:
    settings = get_settings()
    configured = (settings.provider or "auto").strip().lower()

    if configured != "auto":
        if configured not in PROVIDERS:
            raise LLMError(
                f"BOARDLENS_PROVIDER is '{configured}', which is not a known provider. "
                f"Choose one of: {', '.join(PROVIDERS)}, or 'auto'."
            )
        return configured

    detected = detect_provider()
    if detected is None:
        raise LLMError(
            "No model provider credentials were found, so the briefing cannot be "
            "generated. Set one of ANTHROPIC_API_KEY, GEMINI_API_KEY or GROQ_API_KEY "
            "in the environment and restart BoardLens."
        )
    return detected


def model_for(name: str) -> str:
    settings = get_settings()
    return {
        "anthropic": settings.model,
        "gemini": settings.gemini_model,
        "groq": settings.groq_model,
    }[name]


def build_provider(name: str) -> Provider:
    model = model_for(name)

    if name == "anthropic":
        from .anthropic_provider import AnthropicProvider

        return AnthropicProvider(model)

    if name == "gemini":
        from .gemini_provider import GeminiProvider

        return GeminiProvider(model)

    if name == "groq":
        from .groq_provider import GroqProvider

        return GroqProvider(model)

    raise LLMError(f"Unknown provider '{name}'.")


def get_provider() -> Provider:
    """The active provider, constructed once per process."""
    global _provider
    with _lock:
        if _provider is None:
            name = resolve_provider_name()
            _provider = build_provider(name)
            log.info("Model provider: %s", _provider.describe())
        return _provider


def reset_provider() -> None:
    """Drop the cached provider. Used by tests and after a config change."""
    global _provider
    with _lock:
        _provider = None


__all__ = [
    "PROVIDERS",
    "LLMError",
    "Provider",
    "build_provider",
    "detect_provider",
    "get_provider",
    "model_for",
    "reset_provider",
    "resolve_provider_name",
    "strict_schema",
]
