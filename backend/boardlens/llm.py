"""The pipeline's single point of contact with a model.

Everything above this line — the five passes, verification, the exports — is
provider-agnostic and calls only `generate_structured`. Everything below is in
`boardlens/providers/`.

Two invariants hold whichever backend is active:

* Every pass is **structured**. The pipeline never parses prose, so a malformed
  briefing fails at the provider boundary rather than halfway through a DOCX
  export.
* Every failure is raised as `LLMError` carrying a message written for a company
  secretary, because it surfaces on the pack row in the web interface.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

from .config import get_settings
from .providers import LLMError, get_provider, reset_provider, strict_schema

T = TypeVar("T", bound=BaseModel)

__all__ = [
    "LLMError",
    "generate_structured",
    "get_provider",
    "reset_provider",
    "strict_schema",
]


def generate_structured(
    *,
    system: str,
    user: str,
    output_model: type[T],
    effort: str | None = None,
    max_tokens: int = 32_000,
) -> T:
    """Run one structured pass and return a validated model instance."""
    settings = get_settings()
    return get_provider().generate(
        system=system,
        user=user,
        output_model=output_model,
        effort=effort or settings.effort,
        max_tokens=max_tokens,
    )
