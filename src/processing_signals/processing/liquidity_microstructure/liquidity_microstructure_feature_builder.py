"""Presentation-neutral packaging of already calculated Liquidity features."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


def build_liquidity_microstructure_features(*, markets: Mapping[str, Any], whale_activity: Mapping[str, Any],
                                             market_history: Mapping[str, Any], comparison: Mapping[str, Any]) -> dict[str, Any]:
    return deepcopy({"current_orderbooks": {market: data["orderbook"]["timeframes"] for market, data in markets.items()},
                     "order_depth": {market: data["order_depth"]["timeframes"] for market, data in markets.items()},
                     "large_trades": {market: data["large_trades"] for market, data in markets.items()},
                     "whale_activity": whale_activity, "market_history": market_history, "comparison": comparison})


class LiquidityMicrostructureFeatureBuilder:
    def build(self, **kwargs: Any) -> dict[str, Any]:
        return build_liquidity_microstructure_features(**kwargs)
