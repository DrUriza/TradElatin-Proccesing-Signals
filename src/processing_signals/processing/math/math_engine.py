from __future__ import annotations

from typing import Any
import warnings

import pandas as pd

from processing_signals.processing.math.statistics import (
    EXCLUDED_COLUMNS,
    compute_block_statistics,
    last_valid_dict,
    summarize_series,
)
from processing_signals.processing.math.statistical_regimes import build_regime_flags, compute_statistical_regimes
from processing_signals.processing.math.indicators.indicator_engine import compute_ohlcv_indicators
from processing_signals.processing.math.indicators.indicator_engine import IndicatorEngine
from processing_signals.processing.math.microstructure import orderbook_metrics, event_flow_metrics, wall_score_from_orderbook
from processing_signals.processing.patterns.pattern_engine import PatternEngine


class ProcessingMathEngine:
    """
    Processing/Math layer.

    Calculates:
      - technical indicators for OHLCV
      - pure statistical metrics for time-series and events
      - microstructure metrics for order book, large trades, and whale orders
    """

    DEFAULT_WINDOWS = [20, 50, 100]

    def compute_blocks(
        self,
        blocks: list[dict[str, Any]],
        pattern_engine: PatternEngine | None = None,
    ) -> list[dict[str, Any]]:
        pattern_engine = pattern_engine or PatternEngine()
        return [self.compute_block(block, pattern_engine) for block in blocks]

    def compute_block(self, block: dict[str, Any], pattern_engine: PatternEngine) -> dict[str, Any]:
        decision = block.get("classification_input", {})
        if not isinstance(decision, dict):
            decision = {}
        block["decision"] = decision
        if decision.get("structural_data_type") in {"snapshot", "matrix", "heatmap"}:
            block["math"] = self._base_result()
            block["view_math"] = {}
            block["patterns"] = {}
            return block

        allowed_views = set(decision.get("required_views") or [])
        block["math"] = self.compute(block["normalized"], decision)
        block["view_math"] = self.compute_view_math(block.get("transforms", {}), allowed_views=allowed_views)
        block["patterns"] = pattern_engine.detect(
            block["normalized"],
            block["math"],
            decision,
            transforms=block.get("transforms", {}),
            view_math=block.get("view_math", {}),
        )
        return block

    def compute(self, normalized: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        kind = normalized.get("kind")
        result = self._base_result()

        if kind == "candlestick":
            result.update(self._compute_candlestick(normalized, decision))
        elif kind == "orderbook_conventional":
            result.update(self._compute_orderbook(normalized, decision))
        elif kind in {"orderbook_large_trades", "orderbook_whale_orders"}:
            result.update(self._compute_event_list(normalized, decision))

        frame = self._frame_for_statistics(normalized)
        if not frame.empty:
            try:
                with warnings.catch_warnings(record=True) as caught:
                    warnings.simplefilter("always")
                    statistics = compute_block_statistics(
                        frame,
                        windows=self.DEFAULT_WINDOWS,
                        excluded_columns=EXCLUDED_COLUMNS,
                    )
                    regimes = compute_statistical_regimes(
                        frame,
                        windows=self.DEFAULT_WINDOWS,
                        excluded_columns=EXCLUDED_COLUMNS,
                    )

                result["statistics"] = statistics
                regimes["regime_flags"] = build_regime_flags(regimes, statistics)
                result["statistical_regimes"] = regimes
                result["feature_snapshot"].update(statistics.get("last", {}))
                result["warnings"].extend(
                    sorted({f"{warning.category.__name__}: {warning.message}" for warning in caught})
                )
            except Exception as exc:
                result["warnings"].append(f"statistics_failed: {type(exc).__name__}: {exc}")

        return result

    def compute_view_math(self, transforms: dict[str, Any], allowed_views: set[str] | None = None) -> dict[str, Any]:
        """Compute math payloads for transformed OHLC-compatible views."""
        view_math: dict[str, Any] = {}
        indicator_engine = IndicatorEngine()
        for view_name in ["candlestick_derived", "cvd_candlestick_derived"]:
            if allowed_views is not None and view_name not in allowed_views:
                continue
            records = transforms.get(view_name, {}).get("records", [])
            if not records:
                continue
            frame = pd.DataFrame(records)
            if not indicator_engine.is_ohlc_compatible(frame):
                continue
            technical = indicator_engine.compute(frame)
            view_math[view_name] = {
                "technical_indicators": {
                    "columns": list(technical.columns),
                    "last": last_valid_dict(technical),
                }
            }
        return view_math

    @staticmethod
    def _base_result() -> dict[str, Any]:
        return {
            "technical_indicators": {},
            "statistics": {},
            "statistical_regimes": {},
            "microstructure": {},
            "feature_snapshot": {},
            "warnings": [],
        }

    def _compute_candlestick(self, normalized: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        df: pd.DataFrame = normalized["dataframe"]
        result: dict[str, Any] = self._base_result()

        feature_frame = pd.DataFrame(index=df.index)

        if decision.get("apply_technical_indicators"):
            technical_df = compute_ohlcv_indicators(df)
            result["technical_indicators"] = {
                "last": last_valid_dict(technical_df),
                "columns": list(technical_df.columns),
            }
            feature_frame = pd.concat([feature_frame, technical_df], axis=1)

        result["feature_snapshot"] = last_valid_dict(feature_frame)
        return result

    def _compute_orderbook(self, normalized: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        bids: pd.DataFrame = normalized["bids"]
        asks: pd.DataFrame = normalized["asks"]
        if bids.empty or asks.empty or "notional_usdt" not in bids.columns or "notional_usdt" not in asks.columns:
            return {
                "technical_indicators": {},
                "statistics": {},
                "statistical_regimes": {},
                "microstructure": {},
                "feature_snapshot": {},
            }

        micro = orderbook_metrics(bids, asks)
        micro.update(wall_score_from_orderbook(micro))

        # Pure stats over visible liquidity distribution.
        bid_notional_stats = summarize_series(bids["notional_usdt"])
        ask_notional_stats = summarize_series(asks["notional_usdt"])

        feature_snapshot = {**micro}
        feature_snapshot.update({f"bid_notional_{k}": v for k, v in bid_notional_stats.items()})
        feature_snapshot.update({f"ask_notional_{k}": v for k, v in ask_notional_stats.items()})

        return {
            "technical_indicators": {},
            "statistics": {},
            "statistical_regimes": {},
            "microstructure": micro,
            "feature_snapshot": feature_snapshot,
        }

    def _compute_event_list(self, normalized: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        events: pd.DataFrame = normalized["events"]
        flow = event_flow_metrics(events)

        stats = {}
        for column in ["price", "quantity_btc", "notional_usdt", "age_seconds", "active_duration_seconds"]:
            if column in events.columns:
                stats[column] = summarize_series(events[column])

        feature_snapshot = {**flow}
        for name, summary in stats.items():
            feature_snapshot.update({f"{name}_{k}": v for k, v in summary.items()})

        return {
            "technical_indicators": {},
            "statistics": {},
            "statistical_regimes": {},
            "microstructure": flow,
            "feature_snapshot": feature_snapshot,
        }

    def _frame_for_statistics(self, normalized: dict[str, Any]) -> pd.DataFrame:
        if isinstance(normalized.get("dataframe"), pd.DataFrame):
            return normalized["dataframe"].copy()

        if isinstance(normalized.get("events"), pd.DataFrame):
            return normalized["events"].copy()

        bids = normalized.get("bids")
        asks = normalized.get("asks")
        if isinstance(bids, pd.DataFrame) and isinstance(asks, pd.DataFrame):
            bid_df = bids.add_prefix("bid_").reset_index(drop=True)
            ask_df = asks.add_prefix("ask_").reset_index(drop=True)
            return pd.concat([bid_df, ask_df], axis=1)

        return pd.DataFrame()
