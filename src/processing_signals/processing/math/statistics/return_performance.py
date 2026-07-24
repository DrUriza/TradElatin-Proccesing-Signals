from __future__ import annotations

import math
from typing import Iterable

from .descriptive_statistics import calculate_mean, calculate_standard_deviation, finite_values


def calculate_simple_returns(close_values: Iterable[float | None]) -> list[float | None]:
    closes = list(close_values)
    output: list[float | None] = [None] * len(closes)
    for index in range(1, len(closes)):
        previous, current = closes[index - 1], closes[index]
        if previous is None or current is None:
            continue
        previous, current = float(previous), float(current)
        if previous != 0 and math.isfinite(previous) and math.isfinite(current):
            output[index] = current / previous - 1.0
    return output


def calculate_log_returns(close_values: Iterable[float | None]) -> list[float | None]:
    simple = calculate_simple_returns(close_values)
    return [None if value is None or value <= -1 else math.log1p(value) for value in simple]


def _max_streak(returns: Iterable[float | None], positive: bool) -> int:
    best = current = 0
    for value in finite_values(returns):
        matches = value > 0 if positive else value < 0
        current = current + 1 if matches else 0
        best    = max(best, current)
    return best


def calculate_max_consecutive_wins(returns: Iterable[float | None]) -> int:
    return _max_streak(returns, True)


def calculate_max_consecutive_losses(returns: Iterable[float | None]) -> int:
    return _max_streak(returns, False)


def calculate_omega_ratio(returns: Iterable[float | None], threshold_return: float = 0.0) -> float | None:
    clean  = finite_values(returns)
    gains  = sum(max(value - threshold_return, 0.0) for value in clean)
    losses = sum(max(threshold_return - value, 0.0) for value in clean)
    return gains / losses if losses > 0 else None


def calculate_sharpe_ratio(returns: Iterable[float | None], risk_free_rate: float = 0.0, periods_per_year: int = 365) -> float | None:
    clean = finite_values(returns)
    if not clean or periods_per_year <= 0:
        return None
    periodic_rf = risk_free_rate / periods_per_year
    excess      = [value - periodic_rf for value in clean]
    deviation   = calculate_standard_deviation(excess, ddof=1)
    mean        = calculate_mean(excess)
    return mean / deviation * math.sqrt(periods_per_year) if mean is not None and deviation not in (None, 0) else None


def calculate_sortino_ratio(returns: Iterable[float | None], target_return: float = 0.0, periods_per_year: int = 365) -> float | None:
    clean    = finite_values(returns)
    downside = [min(value - target_return, 0.0) ** 2 for value in clean]
    if not clean or not downside:
        return None
    downside_deviation = math.sqrt(sum(downside) / len(downside))
    mean               = calculate_mean([value - target_return for value in clean])
    return mean / downside_deviation * math.sqrt(periods_per_year) if mean is not None and downside_deviation > 0 else None


def calculate_equity_curve(returns: Iterable[float | None], initial_value: float = 1.0) -> list[float]:
    equity = float(initial_value)
    output = []
    for value in returns:
        if value is not None and math.isfinite(float(value)):
            equity *= 1.0 + float(value)
        output.append(equity)
    return output


def calculate_max_drawdown(equity_curve: Iterable[float | None]) -> float | None:
    clean = finite_values(equity_curve)
    if not clean:
        return None
    peak    = clean[0]
    maximum = 0.0
    for value in clean:
        peak = max(peak, value)
        if peak > 0:
            maximum = min(maximum, value / peak - 1.0)
    return maximum


def calculate_calmar_ratio(returns: Iterable[float | None], max_drawdown: float | None, periods_per_year: int) -> float | None:
    clean = finite_values(returns)
    mean  = calculate_mean(clean)
    if mean is None or max_drawdown in (None, 0):
        return None
    return mean * periods_per_year / abs(max_drawdown)


def calculate_profit_factor(returns: Iterable[float | None]) -> float | None:
    clean  = finite_values(returns)
    gains  = sum(value for value in clean if value > 0)
    losses = abs(sum(value for value in clean if value < 0))
    return gains / losses if losses > 0 else None


def calculate_recovery_factor(returns: Iterable[float | None], max_drawdown: float | None) -> float | None:
    clean = finite_values(returns)
    if max_drawdown in (None, 0) or not clean:
        return None
    cumulative_return = calculate_equity_curve(clean)[-1] - 1.0
    return cumulative_return / abs(max_drawdown)


def calculate_win_rate(returns: Iterable[float | None]) -> float | None:
    clean = [value for value in finite_values(returns) if value != 0]
    return sum(value > 0 for value in clean) / len(clean) if clean else None
