from __future__ import annotations

import math
from statistics import fmean, stdev
from typing     import Iterable


def finite_values(values: Iterable[float | None]) -> list[float]:
    output = []
    for value in values:
        if value is not None:
            number = float(value)
            if math.isfinite(number):
                output.append(number)
    return output


def calculate_mean(values: Iterable[float | None]) -> float | None:
    clean = finite_values(values)
    return fmean(clean) if clean else None


def calculate_standard_deviation(values: Iterable[float | None], ddof: int = 1) -> float | None:
    clean = finite_values(values)
    if ddof < 0 or len(clean) <= ddof:
        return None
    mean = fmean(clean)
    return math.sqrt(sum((value - mean) ** 2 for value in clean) / (len(clean) - ddof))


def calculate_skewness(values: Iterable[float | None]) -> float | None:
    clean = finite_values(values)
    n     = len(clean)
    if n < 3:
        return None
    mean = fmean(clean)
    m2   = sum((value - mean) ** 2 for value in clean) / n
    if m2 == 0:
        return None
    m3 = sum((value - mean) ** 3 for value in clean) / n
    return math.sqrt(n * (n - 1)) / (n - 2) * (m3 / (m2 ** 1.5))


def calculate_kurtosis(values: Iterable[float | None], mode: str = "pearson") -> float | None:
    clean = finite_values(values)
    n     = len(clean)
    if n < 4:
        return None
    mean = fmean(clean)
    m2   = sum((value - mean) ** 2 for value in clean) / n
    if m2 == 0:
        return None
    m4     = sum((value - mean) ** 4 for value in clean) / n
    excess = ((n - 1) / ((n - 2) * (n - 3))) * ((n + 1) * (m4 / (m2 * m2) - 3) + 6)
    if mode == "excess":
        return excess
    if mode == "pearson":
        return excess + 3.0
    raise ValueError("mode must be 'pearson' or 'excess'")


def calculate_z_score(values: Iterable[float | None], lookback: int = 100, ddof: int = 1) -> float | None:
    clean     = finite_values(values)
    window    = clean[-lookback:]
    deviation = calculate_standard_deviation(window, ddof=ddof)
    mean      = calculate_mean(window)
    if mean is None or deviation in (None, 0):
        return None
    return (window[-1] - mean) / deviation
