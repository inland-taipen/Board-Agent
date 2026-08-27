"""Provider-independent pieces of the model call.

BoardLens asks one thing of a model provider: given a system prompt, a user
prompt and a Pydantic model, return a validated instance of that model. Nothing
else in the pipeline touches the provider, so adding one means implementing a
single method.

The JSON schema built here is deliberately strict — every property required,
every object closed. That is not a stylistic choice: an optional field in a
strict schema invites the model to omit the awkward ones, and the awkward field
in a board briefing is always `evidence`. The same hardening happens to satisfy
Anthropic's `json_schema` format and Groq's `strict: true` mode, which impose
the same requirements.
"""

from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


# `.env.example` ships placeholders. Once that file is loaded into the
# environment they are non-empty strings, so a leftover
# `ANTHROPIC_API_KEY=sk-ant-...` would win auto-detection and fail every pass.
# Recognise the obvious ones rather than sending them to a provider.
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


class LLMError(RuntimeError):
    """Raised when a pass cannot be completed.

    Carries a message intended for a company secretary, not a developer - it
    surfaces on the pack row in the web interface.
    """


class Provider(ABC):
    """One model backend."""

    name: str = "provider"

    @abstractmethod
    def generate(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        effort: str,
        max_tokens: int,
    ) -> T:
        """Run one structured pass and return a validated model instance."""

    @abstractmethod
    def describe(self) -> str:
        """One line naming the provider and model, for the startup log."""


def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Produce a strict, self-contained JSON schema for a Pydantic model.

    Pydantic emits `$ref`/`$defs` for nested models. Inlining them and forcing
    `additionalProperties: false` throughout gives providers the flat, closed
    schema that constrained decoding requires.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    return _harden(_inline(raw, defs))


def _inline(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            target = defs.get(ref.split("/")[-1], {})
            merged = _inline(dict(target), defs)
            # Keep sibling keys such as `description` that sit alongside $ref.
            for key, value in node.items():
                if key != "$ref":
                    merged[key] = _inline(value, defs)
            return merged
        return {k: _inline(v, defs) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline(v, defs) for v in node]
    return node


def _harden(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _harden(v) for k, v in node.items()}
        if node.get("type") == "object":
            node["additionalProperties"] = False
            props = node.get("properties")
            if isinstance(props, dict):
                node["required"] = list(props)
        # `title` and `default` add tokens without constraining anything.
        node.pop("title", None)
        return node
    if isinstance(node, list):
        return [_harden(v) for v in node]
    return node


def parse_or_raise(text: str, output_model: type[T], *, provider: str) -> T:
    """Validate a provider's JSON response against the expected model."""
    if not text or not text.strip():
        raise LLMError(f"{provider} returned an empty response.")
    try:
        return output_model.model_validate(json.loads(text))
    except (json.JSONDecodeError, ValidationError) as exc:
        raise LLMError(
            f"{provider} returned a response that did not match the expected "
            f"schema for {output_model.__name__}: {exc}"
        ) from exc


def log_usage(provider: str, model: str, **counts: Any) -> None:
    parts = " ".join(f"{key}={value}" for key, value in counts.items() if value is not None)
    log.info("pass complete provider=%s model=%s %s", provider, model, parts)
