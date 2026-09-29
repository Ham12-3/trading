"""Validated backtest configuration (``config/backtest.yaml``)."""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

BACKTEST_CONFIG_PATH = Path("config/backtest.yaml")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SignalSource(_Strict):
    model: str
    prompt_version: str


class Period(_Strict):
    start: date
    end: date

    def contains(self, d: date) -> bool:
        return self.start <= d <= self.end


class Periods(_Strict):
    in_sample: Period
    out_of_sample: Period

    @model_validator(mode="after")
    def _ordered(self) -> "Periods":
        if self.in_sample.end >= self.out_of_sample.start:
            raise ValueError("out_of_sample must start after in_sample ends")
        return self


class Weights(_Strict):
    guidance: float
    tone: float
    revenue: float
    eps: float


class Composite(_Strict):
    weights: Weights
    tone_center: float | Literal["in_sample_median"]
    long_threshold: float
    short_threshold: float


class Baselines(_Strict):
    opening_gap_threshold: float = Field(ge=0)
    eps_surprise_threshold: float = Field(default=0.02, ge=0)


class Combined(_Strict):
    eps_surprise_weight: float = 1.0


class PortfolioConfig(_Strict):
    hold_days: int = Field(ge=0, le=20)
    max_positions: int = Field(ge=1)
    hedge_with_benchmark: bool
    cost_bps_per_side: float = Field(ge=0)


class Tuning(_Strict):
    thresholds: list[float]
    tone_weights: list[float]


class BacktestConfig(_Strict):
    signals: SignalSource
    periods: Periods
    composite: Composite
    baselines: Baselines
    combined: Combined = Combined()
    portfolio: PortfolioConfig
    tuning: Tuning


def load_backtest_config(path: Path = BACKTEST_CONFIG_PATH) -> BacktestConfig:
    return BacktestConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
