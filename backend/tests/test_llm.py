"""Tests for the model-call layer.

No network here. What is worth testing without an API key is the schema every
provider is constrained by - if it is malformed, every pass fails at the
provider boundary - plus provider selection and the credential errors, whose
whole purpose is to turn an opaque SDK failure into an instruction a company
secretary can act on.
"""

from __future__ import annotations

import pytest

from boardlens import llm, providers
from boardlens.brief.schema import BoardBriefing, DocumentDigest, ReconciliationBatch
from boardlens.config import get_settings
from boardlens.providers.base import LLMError, parse_or_raise, strict_schema


@pytest.fixture(autouse=True)
def _clear_provider():
    providers.reset_provider()
    yield
    providers.reset_provider()


@pytest.fixture
def no_keys(monkeypatch):
    for key in (
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


# --- schema ------------------------------------------------------------------


@pytest.mark.parametrize("model", [BoardBriefing, DocumentDigest, ReconciliationBatch])
def test_schema_is_strict_and_self_contained(model):
    """The shape Anthropic's json_schema and Groq's strict mode both require."""
    schema = strict_schema(model)

    assert "$defs" not in schema
    assert _no_refs(schema), f"{model.__name__} schema still contains a $ref"
    _assert_closed(schema)


def _assert_closed(node) -> None:
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
        for value in node.values():
            _assert_closed(value)
    elif isinstance(node, list):
        for value in node:
            _assert_closed(value)


def _no_refs(node) -> bool:
    if isinstance(node, dict):
        if "$ref" in node:
            return False
        return all(_no_refs(v) for v in node.values())
    if isinstance(node, list):
        return all(_no_refs(v) for v in node)
    return True


def test_every_briefing_item_carries_an_evidence_array():
    schema = strict_schema(BoardBriefing)

    for section in (
        "critical_risks",
        "unresolved_actions",
        "performance_changes",
        "management_questions",
        "decisions_required",
    ):
        item = schema["properties"][section]["items"]
        assert "evidence" in item["properties"], f"{section} items can omit citations"
        assert item["properties"]["evidence"]["type"] == "array"
        assert "evidence" in item["required"]


def test_malformed_provider_output_is_rejected_with_context():
    with pytest.raises(LLMError) as raised:
        parse_or_raise("{not json", DocumentDigest, provider="Groq")
    assert "Groq" in str(raised.value)
    assert "DocumentDigest" in str(raised.value)

    with pytest.raises(LLMError):
        parse_or_raise("", DocumentDigest, provider="Gemini")


# --- provider selection ------------------------------------------------------


def test_auto_detection_prefers_the_best_fit_for_a_board_pack(monkeypatch, no_keys):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_0000000000000000000000000000000000000000000000000000")
    assert providers.detect_provider() == "groq"

    # Gemini outranks Groq: 1M context against 131K.
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy0000000000000000000000000000000000")
    assert providers.detect_provider() == "gemini"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-0000000000000000000000000000000000000000")
    assert providers.detect_provider() == "anthropic"


def test_no_credentials_anywhere_names_all_three(monkeypatch, no_keys):
    monkeypatch.setenv("BOARDLENS_PROVIDER", "auto")
    get_settings.cache_clear()

    with pytest.raises(LLMError) as raised:
        providers.resolve_provider_name()

    message = str(raised.value)
    assert "ANTHROPIC_API_KEY" in message
    assert "GEMINI_API_KEY" in message
    assert "GROQ_API_KEY" in message


def test_an_explicit_provider_overrides_detection(monkeypatch, no_keys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-0000000000000000000000000000000000000000")
    monkeypatch.setenv("BOARDLENS_PROVIDER", "groq")
    get_settings.cache_clear()

    # Pinning must win even though a higher-ranked credential is present -
    # otherwise a stray key silently changes which model writes the briefing.
    assert providers.resolve_provider_name() == "groq"


def test_an_unknown_provider_name_is_rejected(monkeypatch):
    monkeypatch.setenv("BOARDLENS_PROVIDER", "openai")
    get_settings.cache_clear()

    with pytest.raises(LLMError) as raised:
        providers.resolve_provider_name()
    assert "anthropic" in str(raised.value)


def test_each_provider_reports_a_missing_key_actionably(monkeypatch, no_keys):
    for name, expected in (
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("gemini", "GEMINI_API_KEY"),
        ("groq", "GROQ_API_KEY"),
    ):
        with pytest.raises(LLMError) as raised:
            providers.build_provider(name)
        assert expected in str(raised.value), f"{name} did not name its env var"


def test_model_ids_come_from_settings(monkeypatch):
    monkeypatch.setenv("BOARDLENS_GEMINI_MODEL", "gemini-3.1-pro-preview")
    monkeypatch.setenv("BOARDLENS_GROQ_MODEL", "openai/gpt-oss-20b")
    get_settings.cache_clear()

    assert providers.model_for("gemini") == "gemini-3.1-pro-preview"
    assert providers.model_for("groq") == "openai/gpt-oss-20b"
    assert providers.model_for("anthropic") == get_settings().model


# --- the facade --------------------------------------------------------------


def test_generate_structured_delegates_to_the_active_provider(monkeypatch):
    """The pipeline calls one function; the provider is entirely behind it."""
    seen: dict = {}

    class Stub:
        def describe(self) -> str:
            return "stub / test-model"

        def generate(self, *, system, user, output_model, effort, max_tokens):
            seen.update(
                system=system, user=user, model=output_model, effort=effort, cap=max_tokens
            )
            return DocumentDigest(
                document_purpose="ok",
                key_points=[],
                risks_flagged=[],
                decisions_sought=[],
                figures_of_note=[],
                anomalies=[],
            )

    monkeypatch.setattr(providers, "_provider", Stub())
    monkeypatch.setattr(llm, "get_provider", lambda: Stub())

    result = llm.generate_structured(
        system="SYS", user="USR", output_model=DocumentDigest, effort="low", max_tokens=999
    )

    assert result.document_purpose == "ok"
    assert seen["system"] == "SYS"
    assert seen["effort"] == "low"
    assert seen["cap"] == 999


def test_effort_falls_back_to_the_configured_default(monkeypatch):
    captured: dict = {}

    class Stub:
        def generate(self, *, system, user, output_model, effort, max_tokens):
            captured["effort"] = effort
            return DocumentDigest(
                document_purpose="ok",
                key_points=[],
                risks_flagged=[],
                decisions_sought=[],
                figures_of_note=[],
                anomalies=[],
            )

    monkeypatch.setattr(llm, "get_provider", lambda: Stub())
    llm.generate_structured(system="s", user="u", output_model=DocumentDigest)

    assert captured["effort"] == get_settings().effort


# --- Groq specifics ----------------------------------------------------------


def test_groq_strict_mode_is_limited_to_models_that_support_it():
    from boardlens.providers.groq_provider import STRICT_MODELS

    # Guarding this matters: a non-strict model returns best-effort JSON that
    # eventually fails validation mid-run rather than at configuration time.
    assert "openai/gpt-oss-120b" in STRICT_MODELS
    assert "llama-3.3-70b-versatile" not in STRICT_MODELS


def test_placeholder_credentials_are_ignored_not_used(monkeypatch, no_keys):
    """`.env.example` ships `sk-ant-...`; a leftover must not win detection.

    Before this, copying .env.example and filling in only GEMINI_API_KEY left a
    non-empty ANTHROPIC_API_KEY that auto-detection preferred - so every pass
    failed against a provider the user had never configured.
    """
    from boardlens.providers.base import is_placeholder

    for value in ("sk-ant-...", "", "   ", "your-api-key", "changeme", "..."):
        assert is_placeholder(value), f"{value!r} should be rejected"

    assert not is_placeholder("AIzaSy0000000000000000000000000000000000")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-...")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSy0000000000000000000000000000000000")
    assert providers.detect_provider() == "gemini"
