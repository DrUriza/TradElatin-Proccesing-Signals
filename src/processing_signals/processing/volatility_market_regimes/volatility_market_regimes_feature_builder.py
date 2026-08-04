from __future__ import annotations

from copy   import deepcopy
from typing import Any, Mapping


def build_positioning_features(package: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(package))


def build_volatility_comparison_features(package: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(package))


def build_spread_metric_features(package: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(package))


def build_daily_regime_basis_features(package: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy(dict(package))


def build_volatility_market_regimes_features(
    positioning: Mapping[str, Any],
    volatility_comparison: Mapping[str, Any],
    spread_metrics: Mapping[str, Any],
    daily_regime_basis: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "positioning": build_positioning_features(positioning),
        "volatility_comparison": build_volatility_comparison_features(volatility_comparison),
        "spread_metrics": build_spread_metric_features(spread_metrics),
        "daily_regime_basis": build_daily_regime_basis_features(daily_regime_basis),
    }


class VolatilityMarketRegimesFeatureBuilder:
    def build(
        self,
        positioning: Mapping[str, Any],
        volatility_comparison: Mapping[str, Any],
        spread_metrics: Mapping[str, Any],
        daily_regime_basis: Mapping[str, Any],
    ) -> dict[str, Any]:
        return build_volatility_market_regimes_features(positioning, volatility_comparison, spread_metrics, daily_regime_basis)
