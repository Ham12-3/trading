"""LLM providers behind one small interface. OpenAI is implemented; others can be added."""

import time
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """The provider rejected the request or failed (not a rate limit)."""


class RateLimitedError(RuntimeError):
    """The provider asked us to slow down; the caller backs off and retries."""


@dataclass(frozen=True)
class LLMResponse:
    text: str  # raw JSON text; validated by the caller, never trusted
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int  # includes any hidden reasoning tokens (they are billed as output)
    latency_ms: int


class LLMProvider(Protocol):
    def complete(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LLMResponse:
        """One structured-output call. Raises ``RateLimitedError`` or ``ProviderError``."""
        ...


class OpenAIProvider:
    """OpenAI Responses API with strict JSON-schema structured output."""

    def __init__(self, api_key: str, *, timeout_seconds: float = 120.0) -> None:
        import openai

        self._openai = openai
        # SDK-level retries off: rate-limit backoff is handled (and counted) by the runner.
        self._client = openai.OpenAI(api_key=api_key, max_retries=0, timeout=timeout_seconds)

    def complete(
        self, *, model: str, system: str, user: str, schema: dict[str, Any], max_output_tokens: int
    ) -> LLMResponse:
        started = time.perf_counter()
        try:
            resp = self._client.responses.create(
                model=model,
                instructions=system,
                input=user,
                max_output_tokens=max_output_tokens,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": "announcement_signals",
                        "schema": schema,
                        "strict": True,
                    }
                },
            )
        except self._openai.RateLimitError as exc:
            raise RateLimitedError(str(exc)) from exc
        except self._openai.APIError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        latency_ms = int((time.perf_counter() - started) * 1000)
        if resp.status != "completed":
            reason = getattr(resp.incomplete_details, "reason", None)
            raise ProviderError(f"response status {resp.status} ({reason})")
        usage = resp.usage
        cached = usage.input_tokens_details.cached_tokens if usage else 0
        return LLMResponse(
            text=resp.output_text,
            input_tokens=usage.input_tokens if usage else 0,
            cached_input_tokens=cached or 0,
            output_tokens=usage.output_tokens if usage else 0,
            latency_ms=latency_ms,
        )


def make_provider(name: str, api_keys: dict[str, str | None]) -> LLMProvider:
    """Build a provider by name; fail clearly when its API key is missing."""
    if name == "openai":
        key = api_keys.get("openai")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not set in .env")
        return OpenAIProvider(key)
    raise ProviderError(f"provider {name!r} is not implemented")
