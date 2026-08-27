"""Groq backend.

Fast and cheap, on open models. Two constraints matter for a board pack, and
both are stated here rather than discovered during a pilot:

* **131K context**, against 1M on the other two providers. The pipeline already
  windows every pass, so this fits - but the synthesis pass is the one that
  grows with pack size, and a very large pack can approach the ceiling. If it
  does, lower the evidence budgets in `brief/generator.py`.
* **Strict mode is limited to specific models.** Only those models guarantee
  schema adherence by constrained decoding; anything else is best-effort JSON
  and will eventually return a shape the pipeline rejects.

Groq's strict-mode schema requirements - every property required, every object
closed - are exactly what `strict_schema()` already produces, so the schema
crosses over unchanged.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .base import LLMError, Provider, credential_for, log_usage, parse_or_raise, strict_schema

T = TypeVar("T", bound=BaseModel)

# Models that support `strict: true` constrained decoding. Anything outside
# this set is best-effort JSON, which is not good enough for a pipeline that
# treats a malformed response as a failed pass.
STRICT_MODELS = frozenset(
    {
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
        "qwen/qwen3.8-27b",
    }
)

# gpt-oss exposes reasoning effort with three levels; the pipeline's five map
# onto them rather than being dropped.
_EFFORT = {
    "low": "low",
    "medium": "medium",
    "high": "high",
    "xhigh": "high",
    "max": "high",
}


class GroqProvider(Provider):
    name = "groq"

    def __init__(self, model: str) -> None:
        self.model = model

        if not credential_for(("GROQ_API_KEY",)):
            raise LLMError(
                "No Groq API credentials are configured. Set GROQ_API_KEY "
                "(https://console.groq.com/keys), or switch provider with "
                "BOARDLENS_PROVIDER=anthropic or gemini."
            )

        try:
            from groq import Groq
        except ImportError as exc:
            raise LLMError(
                "The Groq provider is selected but the groq SDK is not installed. "
                "Run: pip install -e '.[groq]'"
            ) from exc

        self.client = Groq(max_retries=3, timeout=900.0)
        self.strict = model in STRICT_MODELS

    def describe(self) -> str:
        mode = "strict" if self.strict else "best-effort JSON (schema not guaranteed)"
        return f"groq / {self.model} [{mode}]"

    def generate(
        self,
        *,
        system: str,
        user: str,
        output_model: type[T],
        effort: str,
        max_tokens: int,
    ) -> T:
        schema = strict_schema(output_model)

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_model.__name__,
                        "strict": self.strict,
                        "schema": schema,
                    },
                },
                reasoning_effort=_EFFORT.get(effort, "medium"),
                max_completion_tokens=max_tokens,
            )
        except Exception as exc:
            raise LLMError(_explain(exc)) from exc

        usage = getattr(response, "usage", None)
        if usage is not None:
            log_usage(
                self.name,
                self.model,
                input=getattr(usage, "prompt_tokens", None),
                output=getattr(usage, "completion_tokens", None),
            )

        choice = response.choices[0]
        if getattr(choice, "finish_reason", None) == "length":
            raise LLMError(
                "Groq hit the output limit before completing the structured response. "
                "Reduce the evidence budget for this pass or raise max_tokens."
            )

        return parse_or_raise(choice.message.content or "", output_model, provider="Groq")


def _explain(exc: Exception) -> str:
    message = str(exc)
    lowered = message.lower()

    if "api key" in lowered or "401" in lowered or "unauthorized" in lowered:
        return "Groq rejected the credentials. Check GROQ_API_KEY at https://console.groq.com/keys."
    if "rate limit" in lowered or "429" in lowered:
        return "Groq rate limit reached. Retry in a few minutes."
    if "context" in lowered and ("length" in lowered or "window" in lowered):
        return (
            "The request exceeded Groq's 131K context window. Board packs this large "
            "need smaller evidence budgets (see DIGEST_WINDOW_CHARS and "
            "SECTION_EVIDENCE_CHARS in brief/generator.py) or a longer-context provider."
        )
    if "does not exist" in lowered or "not found" in lowered or "404" in lowered:
        return (
            "Groq does not recognise the configured model. Check BOARDLENS_GROQ_MODEL "
            "against https://console.groq.com/docs/models."
        )
    return f"Groq API error: {message}"
