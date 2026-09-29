"""Performance metrics on a daily return series. Pure functions; 252 trading days per year."""

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def equity_curve(daily_returns: pd.Series) -> pd.Series:
    """Compounded equity starting at 1.0."""
    return (1.0 + daily_returns).cumprod()


def drawdown(equity: pd.Series) -> pd.Series:
    """Fractional drawdown from the running peak (0 at a new high, negative below it)."""
    peak = equity.cummax().clip(lower=1.0)  # the curve starts from 1.0 of capital
    return equity / peak - 1.0


def annualised_return(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    final = float(np.prod(1.0 + daily_returns.to_numpy(dtype=float)))
    if final <= 0:
        return -1.0
    return float(final ** (TRADING_DAYS / len(daily_returns)) - 1.0)


def annualised_volatility(daily_returns: pd.Series) -> float:
    if len(daily_returns) < 2:
        return 0.0
    return float(daily_returns.std(ddof=1)) * math.sqrt(TRADING_DAYS)


def sharpe_ratio(daily_returns: pd.Series) -> float | None:
    """Annualised Sharpe with a zero risk-free rate; ``None`` when volatility is zero."""
    if len(daily_returns) < 2:
        return None
    sd = float(daily_returns.std(ddof=1))
    if sd == 0.0:
        return None
    return float(daily_returns.mean()) / sd * math.sqrt(TRADING_DAYS)


def max_drawdown(daily_returns: pd.Series) -> float:
    if daily_returns.empty:
        return 0.0
    return float(drawdown(equity_curve(daily_returns)).min())
