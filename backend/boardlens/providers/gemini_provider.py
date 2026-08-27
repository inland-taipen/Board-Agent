"""Google Gemini backend.

The closest substitute for the reference implementation: a frontier model with a
long context window and first-class structured output. The Pydantic model is
handed to the SDK directly as `response_schema`, so the schema hardening the
other providers need is not required here.

Two capabilities are lost relative to Anthropic, and neither breaks the
pipeline:

* No prompt caching across passes. Every pass re-sends its system prompt, which
  costs tokens but changes no output.
* No effort control. `effort` is accepted and ignored rather than mapped onto a
  thinking budget, because a wrong mapping is worse than none - choose the
  model tier instead (Pro for production, Flash for a fast pilot loop).
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .base import LLMError, Provider, credential_for, log_usage, parse_or_raise

T = TypeVar("T", bound=BaseModel)

# Either name works; the SDK reads both, and GOOGLE_API_KEY takes precedence.
_ENV_KEYS = ("GEMINI_API_KEY", "GOOGLE_API_KEY")


class GeminiProvider(Provider):
    name = "gemini"

    def __init__(self, model: str) -> None:
        self.model = model

        if not credential_for(_ENV_KEYS):
            raise LLMError(
                "No Gemini API credentials are configured. Set GEMINI_API_KEY "
                "(https://aistudio.google.com/apikey), or switch provider with "
                "BOARDLENS_PROVIDER=anthropic or groq."
            )

        try:
            from google import genai
        except ImportError as exc:
            raise LLMError(
                "The Gemini provider is selected but google-genai is not installed. "
                "Run: pip install -e '.[gemini]'"
            ) from exc

        self._genai = genai
        self.client = genai.Client()

    def describe(self) -> str:
        return f"gemini / {self.model}"

    def generate(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        effort: str,
        max_tokens: int,
    ) -> T:
        from google.genai import types

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    # The SDK accepts a Pydantic model directly and derives the
                    # schema itself, which avoids a second schema dialect to keep
                    # in step with `brief/schema.py`.
                    response_schema=output_model,
                    max_output_tokens=max_tokens,
                ),
            )
        except Exception as exc:
            raise LLMError(_explain(exc)) from exc

        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            log_usage(
                self.name,
                self.model,
                input=getattr(usage, "prompt_token_count", None),
                output=getattr(usage, "candidates_token_count", None),
            )

        # `response.parsed` exists on recent SDKs but is not guaranteed across
        # versions, so the JSON text is validated against the model directly -
        # the same path every other provider takes.
        return parse_or_raise(response.text or "", output_model, provider="Gemini")


def _explain(exc: Exception) -> str:
    """Turn an SDK exception into something a company secretary can act on."""
    message = str(exc)
    lowered = message.lower()

    if "api key" in lowered or "unauthenticated" in lowered or "permission" in lowered:
        return (
            "Gemini rejected the credentials. Check GEMINI_API_KEY at "
            "https://aistudio.google.com/apikey."
        )
    if "quota" in lowered or "429" in lowered or "resource_exhausted" in lowered:
        return (
            "Gemini quota exhausted while generating the briefing. Retry later, or "
            "use a model tier with more headroom."
        )
    if "not found" in lowered or "404" in lowered:
        return (
            "Gemini does not recognise the configured model. Check "
            "BOARDLENS_GEMINI_MODEL against https://ai.google.dev/gemini-api/docs/models."
        )
    return f"Gemini API error: {message}"
