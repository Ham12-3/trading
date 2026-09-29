"""Shared API dependencies (overridable in tests)."""

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException

from newsalpha.core.config import get_settings
from newsalpha.extraction.models_config import ModelsConfig, load_models_config
from newsalpha.extraction.providers import LLMProvider, ProviderError, make_provider


@dataclass(frozen=True)
class SignalSource:
    """Which (model, prompt_version) the API shows by default."""

    model: str
    prompt_version: str


@lru_cache
def models_config() -> ModelsConfig:
    return load_models_config()


def default_signal_source() -> SignalSource:
    cfg = models_config()
    return SignalSource(cfg.defaults["bulk"], cfg.defaults.get("prompt_version", "v1"))


def get_provider() -> LLMProvider:
    """Provider for on-demand extraction; 503 when no API key is configured."""
    settings = get_settings()
    price = models_config().price(default_signal_source().model)
    try:
        return make_provider(
            price.provider,
            {"openai": settings.openai_api_key, "anthropic": settings.anthropic_api_key},
        )
    except ProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def data_dir() -> Path:
    return get_settings().data_dir
