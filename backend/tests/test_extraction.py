"""Extraction logic with a scripted provider (no network, no API key)."""

import json
from pathlib import Path
from typing import Any

import pytest

from newsalpha.extraction.extract import SCHEMA, ExtractionOutcome, extract_document, truncate
from newsalpha.extraction.models_config import (
    ExtractionSettings,
    ModelPrice,
    load_models_config,
)
from newsalpha.extraction.prompts import load_prompt
from newsalpha.extraction.providers import LLMResponse, ProviderError, RateLimitedError
from newsalpha.extraction.schema import AnnouncementSignals

BACKEND = Path(__file__).resolve().parents[1]
FIX = Path(__file__).parent / "fixtures" / "llm"
PRICE = ModelPrice(
    provider="fake", input_per_mtok=1.0, cached_input_per_mtok=0.1, output_per_mtok=10.0
)
SETTINGS = ExtractionSettings(
    max_input_tokens=1000,
    max_output_tokens=500,
    concurrency=2,
    rate_limit_retries=3,
    rate_limit_backoff_seconds=1.0,
)


def valid_payload() -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIX / "valid_signals.json").read_text(encoding="utf-8"))
    return payload


def resp(payload: object, *, tokens: tuple[int, int, int] = (1000, 200, 300)) -> LLMResponse:
    text = payload if isinstance(payload, str) else json.dumps(payload)
    return LLMResponse(
        text=text,
        input_tokens=tokens[0],
        cached_input_tokens=tokens[1],
        output_tokens=tokens[2],
        latency_ms=100,
    )


class ScriptedProvider:
    """Returns (or raises) the scripted items in order and records every request."""

    def __init__(self, script: list[object]) -> None:
        self.script = list(script)
        self.calls: list[dict[str, Any]] = []

    def complete(self, **kwargs: Any) -> LLMResponse:
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, LLMResponse)
        return item


def run(
    provider: ScriptedProvider, text: str = "Revenue rose 8%.", sleeps: list[float] | None = None
) -> ExtractionOutcome:
    return extract_document(
        provider=provider,
        model="fake-model",
        prompt=load_prompt("v1", BACKEND / "prompts"),
        company_name="Example Co",
        text=text,
        settings=SETTINGS,
        price=PRICE,
        sleep=(sleeps.append if sleeps is not None else lambda _s: None),
    )


def test_fixture_matches_schema() -> None:
    AnnouncementSignals.model_validate(valid_payload())


def test_strict_schema_requires_every_field_and_forbids_extras() -> None:
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == set(AnnouncementSignals.model_fields)
    assert SCHEMA["properties"]["management_tone"]["minimum"] == -1.0


def test_ok_on_first_attempt_with_cost_and_usage() -> None:
    provider = ScriptedProvider([resp(valid_payload())])
    out = run(provider)
    assert out.status == "ok" and out.attempts == 1
    assert out.payload is not None and out.payload["guidance_direction"] == "raised"
    # (1000 - 200) * 1.0 + 200 * 0.1 + 300 * 10.0 = 3820 per 1M tokens
    assert out.cost_usd == pytest.approx(3820 / 1_000_000)
    assert "Example Co" in provider.calls[0]["user"]
    assert provider.calls[0]["schema"] is SCHEMA


def test_invalid_output_is_retried_once_with_the_error() -> None:
    bad = valid_payload() | {"management_tone": 1.7}
    provider = ScriptedProvider([resp(bad), resp(valid_payload())])
    out = run(provider)
    assert out.status == "ok" and out.attempts == 2
    retry_prompt = provider.calls[1]["user"]
    assert "rejected by the validator" in retry_prompt and "management_tone" in retry_prompt
    assert out.input_tokens == 2000  # both calls are paid for and counted


def test_two_invalid_outputs_mark_the_row_failed() -> None:
    provider = ScriptedProvider([resp("not json"), resp(valid_payload() | {"extra": 1})])
    out = run(provider)
    assert out.status == "failed" and out.attempts == 2 and out.payload is None
    assert out.error is not None and "validation" in out.error
    assert out.cost_usd > 0


def test_provider_error_fails_without_reprompting() -> None:
    provider = ScriptedProvider([ProviderError("400 bad schema")])
    out = run(provider)
    assert out.status == "failed" and len(provider.calls) == 1
    assert out.error is not None and "400 bad schema" in out.error


def test_rate_limit_backs_off_exponentially_then_succeeds() -> None:
    sleeps: list[float] = []
    provider = ScriptedProvider(
        [RateLimitedError("429"), RateLimitedError("429"), resp(valid_payload())]
    )
    out = run(provider, sleeps=sleeps)
    assert out.status == "ok" and sleeps == [1.0, 2.0]


def test_rate_limit_exhaustion_is_a_failure() -> None:
    provider = ScriptedProvider([RateLimitedError("429")] * 4)
    out = run(provider)
    assert out.status == "failed" and "RateLimitedError" in (out.error or "")


def test_truncation_is_flagged_and_disclosed_in_the_prompt() -> None:
    text, cut = truncate("x" * 5000, max_tokens=1000)
    assert cut and len(text) == 4000
    provider = ScriptedProvider([resp(valid_payload())])
    out = run(provider, text="y" * 10_000)
    assert out.truncated
    assert "truncated" in provider.calls[0]["user"]


def test_prompt_rendering_keeps_braces_in_documents() -> None:
    prompt = load_prompt("v1", BACKEND / "prompts")
    user = prompt.render_user(company_name="X", document="EPS {non-GAAP} $1", truncated=False)
    assert "EPS {non-GAAP} $1" in user and "{document}" not in user


def test_bad_prompt_version_is_rejected() -> None:
    with pytest.raises(ValueError, match="look like"):
        load_prompt("../secrets", BACKEND / "prompts")


def test_models_config_has_prices_for_defaults() -> None:
    cfg = load_models_config(BACKEND / "config" / "models.yaml")
    for role in ("bulk", "comparison"):
        assert cfg.price(cfg.defaults[role]).output_per_mtok > 0
    with pytest.raises(KeyError, match="not in config"):
        cfg.price("no-such-model")
