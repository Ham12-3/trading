"""Extract signals from one document: truncate, call, validate, retry once, account for cost."""

import functools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import ValidationError

from newsalpha.extraction.models_config import ExtractionSettings, ModelPrice
from newsalpha.extraction.prompts import Prompt
from newsalpha.extraction.providers import LLMProvider, LLMResponse, ProviderError, RateLimitedError
from newsalpha.extraction.schema import AnnouncementSignals, strict_json_schema

log = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4  # conservative approximation for English prose; budget only, not billing
SCHEMA = strict_json_schema(AnnouncementSignals)


@dataclass
class ExtractionOutcome:
    status: Literal["ok", "failed"] = "failed"
    payload: dict[str, Any] | None = None
    error: str | None = None
    attempts: int = 0
    truncated: bool = False
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    errors: list[str] = field(default_factory=list)

    def add_usage(self, resp: LLMResponse, price: ModelPrice) -> None:
        self.input_tokens += resp.input_tokens
        self.cached_input_tokens += resp.cached_input_tokens
        self.output_tokens += resp.output_tokens
        self.latency_ms += resp.latency_ms
        self.cost_usd += price.cost_usd(
            resp.input_tokens, resp.cached_input_tokens, resp.output_tokens
        )


def truncate(text: str, max_tokens: int) -> tuple[str, bool]:
    """Keep the head of the document (headline numbers and outlook come first in releases)."""
    budget = max_tokens * CHARS_PER_TOKEN
    if len(text) <= budget:
        return text, False
    return text[:budget], True


def _call_with_backoff(
    call: Callable[[], LLMResponse], settings: ExtractionSettings, sleep: Callable[[float], None]
) -> LLMResponse:
    for attempt in range(settings.rate_limit_retries + 1):
        try:
            return call()
        except RateLimitedError:
            if attempt == settings.rate_limit_retries:
                raise
            delay = settings.rate_limit_backoff_seconds * 2**attempt
            log.warning("rate limited; retrying in %.1fs", delay)
            sleep(delay)
    raise AssertionError("unreachable")


def _retry_message(user: str, bad_output: str, error: str) -> str:
    return (
        f"{user}\n\nYour previous answer was rejected by the validator.\n"
        f"Previous answer:\n{bad_output[:4000]}\n\nValidation error:\n{error[:2000]}\n\n"
        "Return a corrected JSON object that satisfies every constraint."
    )


def extract_document(
    *,
    provider: LLMProvider,
    model: str,
    prompt: Prompt,
    company_name: str,
    text: str,
    settings: ExtractionSettings,
    price: ModelPrice,
    sleep: Callable[[float], None] = time.sleep,
) -> ExtractionOutcome:
    """Run one extraction. Never raises for model or API problems; the outcome records them."""
    outcome = ExtractionOutcome()
    document, outcome.truncated = truncate(text, settings.max_input_tokens)
    if outcome.truncated:
        log.info("%s: truncated %d -> %d chars", company_name, len(text), len(document))
    user = prompt.render_user(
        company_name=company_name, document=document, truncated=outcome.truncated
    )

    message = user
    for _ in range(2):  # first try + one retry carrying the validation error
        outcome.attempts += 1
        try:
            call = functools.partial(
                provider.complete,
                model=model,
                system=prompt.system,
                user=message,
                schema=SCHEMA,
                max_output_tokens=settings.max_output_tokens,
            )
            resp = _call_with_backoff(call, settings, sleep)
        except (ProviderError, RateLimitedError) as exc:
            outcome.errors.append(f"{type(exc).__name__}: {exc}")
            break  # an API failure is not something a re-prompt fixes
        outcome.add_usage(resp, price)
        try:
            signals = AnnouncementSignals.model_validate_json(resp.text)
        except ValidationError as exc:
            outcome.errors.append(f"validation: {exc}")
            message = _retry_message(user, resp.text, str(exc))
            continue
        outcome.status = "ok"
        outcome.payload = signals.model_dump(mode="json")
        outcome.error = None
        return outcome

    outcome.error = " | ".join(outcome.errors)[:4000]
    return outcome
