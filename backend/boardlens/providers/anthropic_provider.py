"""Anthropic backend.

The reference implementation and the quality bar the briefing template was
written against. It is the only provider here that supports all three of the
things this pipeline would ideally have: a 1M context window, prompt caching
across passes over one pack, and effort control.
"""

from __future__ import annotations

import os
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel

from .base import LLMError, Provider, credential_for, log_usage, parse_or_raise, strict_schema

T = TypeVar("T", bound=BaseModel)


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, model: str) -> None:
        self.model = model
        # The SDK reads ANTHROPIC_API_KEY itself and does not care whether the
        # value is real, so a leftover placeholder would reach the API and come
        # back as an opaque 401.
        if os.environ.get("ANTHROPIC_API_KEY") and not credential_for(("ANTHROPIC_API_KEY",)):
            raise LLMError(
                "ANTHROPIC_API_KEY is set to a placeholder value. Replace it with a real "
                "key from https://console.anthropic.com/settings/keys, or remove the line "
                "and set BOARDLENS_PROVIDER to a provider you do have a key for."
            )

        client = anthropic.Anthropic(max_retries=3, timeout=900.0)

        # Preflight. With no credentials the SDK constructs happily and then
        # raises a bare TypeError deep inside the first request - which would
        # reach a company secretary as "Could not resolve authentication
        # method". Checking here turns that into an instruction.
        if not (client.api_key or client.auth_token or client.credentials):
            raise LLMError(
                "No Anthropic API credentials are configured. Set ANTHROPIC_API_KEY "
                "(https://console.anthropic.com/settings/keys), or switch provider "
                "with BOARDLENS_PROVIDER=gemini or groq."
            )
        self.client = client

    def describe(self) -> str:
        return f"anthropic / {self.model}"

    def generate(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        effort: str,
        max_tokens: int,
    ) -> T:
        request: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens,
            # The system prompt is a stable cache prefix; the volatile pack
            # content goes last, so repeated passes over one pack reuse it.
            "system": [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            "messages": [{"role": "user", "content": user}],
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": effort,
                "format": {
                    "type": "json_schema",
                    "schema": strict_schema(output_model),
                },
            },
        }

        try:
            # Streaming keeps long syntheses clear of HTTP timeouts.
            with self.client.messages.stream(**request) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "Anthropic rejected the credentials. Check ANTHROPIC_API_KEY."
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(
                "Anthropic rate limit reached while generating the briefing. "
                "Retry in a few minutes, or lower BOARDLENS_EFFORT."
            ) from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"Anthropic API error {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("Could not reach the Anthropic API - check network egress.") from exc
        except anthropic.AnthropicError as exc:
            # Base class, so this must stay last.
            raise LLMError(f"Anthropic API error: {exc}") from exc

        if message.stop_reason == "refusal":
            category = getattr(message.stop_details, "category", None)
            raise LLMError(
                f"The model declined to complete this pass (category: {category}). "
                "This usually indicates unexpected content in the uploaded pack."
            )

        if message.stop_reason == "max_tokens":
            raise LLMError(
                "The model hit the output limit before completing the structured "
                "response. Reduce the evidence budget for this pass or raise max_tokens."
            )

        usage = message.usage
        log_usage(
            self.name,
            self.model,
            input=usage.input_tokens,
            cache_read=getattr(usage, "cache_read_input_tokens", 0),
            cache_write=getattr(usage, "cache_creation_input_tokens", 0),
            output=usage.output_tokens,
        )

        text = next((b.text for b in message.content if b.type == "text"), "")
        return parse_or_raise(text, output_model, provider="Anthropic")
