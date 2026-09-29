"""Model catalogue and extraction settings from ``config/models.yaml``."""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

MODELS_CONFIG_PATH = Path("config/models.yaml")


class ModelPrice(BaseModel):
    provider: str
    input_per_mtok: float = Field(ge=0)
    cached_input_per_mtok: float = Field(ge=0)
    output_per_mtok: float = Field(ge=0)

    def cost_usd(self, input_tokens: int, cached_input_tokens: int, output_tokens: int) -> float:
        """Cost of one call. ``input_tokens`` includes cached tokens, as providers report it."""
        uncached = max(input_tokens - cached_input_tokens, 0)
        return (
            uncached * self.input_per_mtok
            + cached_input_tokens * self.cached_input_per_mtok
            + output_tokens * self.output_per_mtok
        ) / 1_000_000


class ExtractionSettings(BaseModel):
    max_input_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    concurrency: int = Field(ge=1, le=32)
    rate_limit_retries: int = Field(ge=0)
    rate_limit_backoff_seconds: float = Field(gt=0)


class ModelsConfig(BaseModel):
    defaults: dict[str, str]
    extraction: ExtractionSettings
    models: dict[str, ModelPrice]

    def price(self, model: str) -> ModelPrice:
        if model not in self.models:
            raise KeyError(f"model {model!r} is not in config/models.yaml; add its prices first")
        return self.models[model]


def load_models_config(path: Path = MODELS_CONFIG_PATH) -> ModelsConfig:
    return ModelsConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
