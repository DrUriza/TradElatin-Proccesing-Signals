"""Pure statistics for provider series."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any


def clean_zero(value: float | None) -> float | None:
    return 0.0 if value == 0 else value


def absolute_change(current: float, previous: float) -> float:
    return clean_zero(float(current) - float(previous))  # type: ignore[return-value]


def safe_percent_change(current: float, previous: float) -> float | None:
    return None if previous == 0 else clean_zero(100.0 * (current - previous) / abs(previous))


def rolling_mean(values: Sequence[float], lookback: int) -> float | None:
    if lookback <= 0:
        raise ValueError("lookback_must_be_positive")
    return None if len(values) < lookback else clean_zero(sum(values[-lookback:]) / lookback)


def rolling_std(values: Sequence[float], lookback: int) -> float | None:
    mean = rolling_mean(values, lookback)
    if mean is None:
        return None
    return clean_zero(math.sqrt(sum((value - mean) ** 2 for value in values[-lookback:]) / lookback))


def rolling_z_score(values: Sequence[float], lookback: int) -> float | None:
    mean, std = rolling_mean(values, lookback), rolling_std(values, lookback)
    return None if mean is None or std in (None, 0) else clean_zero((values[-1] - mean) / std)


def observation_at_or_before(records: Sequence[Mapping[str, Any]], timestamp: int) -> Mapping[str, Any] | None:
    eligible = [record for record in records if record["timestamp"] <= timestamp]
    return max(eligible, key=lambda record: record["timestamp"]) if eligible else None
