from __future__ import annotations

import math
from typing import Iterable

from .descriptive_statistics import finite_values


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered  = sorted(values)
    position = (len(ordered) - 1) * probability
    lower    = int(math.floor(position))
    upper    = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def calculate_historical_var(returns: Iterable[float | None], confidence_level: float = 0.95) -> float | None:
    if not 0 < confidence_level < 1:
        raise ValueError("confidence_level must be between 0 and 1")
    return _quantile(finite_values(returns), 1.0 - confidence_level)


def calculate_historical_cvar(returns: Iterable[float | None], confidence_level: float = 0.95) -> float | None:
    clean = finite_values(returns)
    var   = calculate_historical_var(clean, confidence_level)
    if var is None:
        return None
    tail = [value for value in clean if value <= var]
    return sum(tail) / len(tail) if tail else None
