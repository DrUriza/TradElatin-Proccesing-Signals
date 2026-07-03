from __future__ import annotations

from typing import Any

import pandas as pd


OFFICIAL_STAT_WINDOWS = [20, 50, 100]


class CandlestickPatternDetector:
    def detect(
        self,
        normalized: dict[str, Any],
        math_result: dict[str, Any],
        transforms: dict[str, Any] | None = None,
        view_math: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        df = normalized.get("dataframe")
        if df is None or df.empty:
            return {}

        if not self._is_ohlc_compatible(df):
            return {}

        candles = self._build_candle_shapes(df)
        single = self._detect_single_candle_patterns(candles)
        two = self._detect_two_candle_patterns(candles)
        three = self._detect_three_candle_patterns(candles)
        continuation = self._detect_continuation_patterns(candles)
        chart = self._detect_chart_patterns(candles, math_result)
        all_patterns = single + two + three + continuation + chart

        return {
            "pattern_groups": {
                "candlestick_patterns": {
                    "single_candle": single,
                    "two_candle": two,
                    "three_candle": three,
                    "continuation_indecision": continuation,
                    "chart_patterns": chart,
                },
                "liquidity_patterns": [],
                "event_patterns": [],
                "mining_patterns": [],
                "onchain_patterns": [],
            },
            "candle_shape": candles[-1] if candles else {},
            "statistical_regime": self._detect_statistical_regimes(math_result),
            "pattern_summary": self._pattern_summary(all_patterns),
            "pattern_inputs": self._build_pattern_inputs(math_result, view_math or {}),
        }

    @staticmethod
    def _is_ohlc_compatible(df: pd.DataFrame) -> bool:
        return {"open", "high", "low", "close"}.issubset(df.columns)

    def _build_candle_shapes(self, df: pd.DataFrame) -> list[dict[str, Any]]:
        candles: list[dict[str, Any]] = []

        for position, (_, row) in enumerate(df.iterrows()):
            open_ = self._float(row["open"])
            high = self._float(row["high"])
            low = self._float(row["low"])
            close = self._float(row["close"])
            if open_ is None or high is None or low is None or close is None:
                continue
            if high < max(open_, close) or low > min(open_, close):
                continue

            candle_range = high - low
            body = abs(close - open_)
            upper_wick = high - max(open_, close)
            lower_wick = min(open_, close) - low

            candle = {
                "timestamp": row.get("timestamp"),
                "index": position,
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "body": body,
                "range": candle_range,
                "upper_wick": upper_wick,
                "lower_wick": lower_wick,
                "body_ratio": body / candle_range if candle_range else 0,
                "upper_wick_ratio": upper_wick / candle_range if candle_range else 0,
                "lower_wick_ratio": lower_wick / candle_range if candle_range else 0,
                "is_bullish": close > open_,
                "is_bearish": close < open_,
                "is_doji": candle_range > 0 and body / candle_range <= 0.1}
            if "volume" in row:
                candle["volume"] = row.get("volume")
            candles.append(candle)

        return candles

    def _detect_single_candle_patterns(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candles:
            return []

        candle = candles[-1]
        patterns: list[dict[str, Any]] = []
        body_ratio = candle["body_ratio"]
        upper_ratio = candle["upper_wick_ratio"]
        lower_ratio = candle["lower_wick_ratio"]
        after_uptrend = self._recent_trend(candles) == "up"
        after_downtrend = self._recent_trend(candles) == "down"

        if body_ratio <= 0.10:
            patterns.append(self._pattern("doji", "single_candle", "neutral", 0.72, candle, candle, "Body is less than or equal to 10% of the candle range."))
        if body_ratio <= 0.10 and lower_ratio >= 0.60 and upper_ratio <= 0.10:
            patterns.append(self._pattern("dragonfly_doji", "single_candle", "bullish", 0.76, candle, candle, "Doji with dominant lower wick and minimal upper wick."))
        if body_ratio <= 0.10 and upper_ratio >= 0.60 and lower_ratio <= 0.10:
            patterns.append(self._pattern("gravestone_doji", "single_candle", "bearish", 0.76, candle, candle, "Doji with dominant upper wick and minimal lower wick."))
        if 0.10 < body_ratio <= 0.35 and upper_ratio >= 0.20 and lower_ratio >= 0.20:
            patterns.append(self._pattern("spinning_top", "single_candle", "neutral", 0.68, candle, candle, "Small body with meaningful upper and lower wicks."))
        if body_ratio >= 0.85 and upper_ratio <= 0.05 and lower_ratio <= 0.05:
            direction = "bullish" if candle["is_bullish"] else "bearish" if candle["is_bearish"] else "neutral"
            patterns.append(self._pattern("marubozu", "single_candle", direction, 0.80, candle, candle, "Large body with minimal upper and lower wicks."))
        if candle["lower_wick"] >= 2 * candle["body"] and candle["upper_wick"] <= candle["body"] and body_ratio <= 0.35:
            confidence = 0.78 if after_downtrend else 0.66
            patterns.append(self._pattern("hammer", "single_candle", "bullish", confidence, candle, candle, "Long lower wick with small body, preferably after downward movement."))
        if candle["upper_wick"] >= 2 * candle["body"] and candle["lower_wick"] <= candle["body"] and body_ratio <= 0.35:
            confidence = 0.74 if after_downtrend else 0.64
            patterns.append(self._pattern("inverted_hammer", "single_candle", "bullish", confidence, candle, candle, "Long upper wick with small body, preferably after downward movement."))
        if candle["upper_wick"] >= 2 * candle["body"] and candle["lower_wick"] <= candle["body"] and body_ratio <= 0.35:
            confidence = 0.78 if after_uptrend else 0.62
            patterns.append(self._pattern("shooting_star", "single_candle", "bearish", confidence, candle, candle, "Long upper wick with small body, preferably after upward movement."))
        if candle["lower_wick"] >= 2 * candle["body"] and candle["upper_wick"] <= candle["body"] and body_ratio <= 0.35:
            confidence = 0.76 if after_uptrend else 0.62
            patterns.append(self._pattern("hanging_man", "single_candle", "bearish", confidence, candle, candle, "Long lower wick with small body, preferably after upward movement."))

        return patterns

    def _detect_two_candle_patterns(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(candles) < 2:
            return []

        previous, current = candles[-2], candles[-1]
        patterns: list[dict[str, Any]] = []
        previous_midpoint = (previous["open"] + previous["close"]) / 2
        tolerance = max(previous["range"], current["range"], 1.0) * 0.002

        if previous["is_bearish"] and current["is_bullish"] and current["open"] <= previous["close"] and current["close"] >= previous["open"]:
            patterns.append(self._pattern("bullish_engulfing", "two_candle", "bullish", 0.82, previous, current, "Current bullish candle fully engulfs previous bearish candle body."))
        if previous["is_bullish"] and current["is_bearish"] and current["open"] >= previous["close"] and current["close"] <= previous["open"]:
            patterns.append(self._pattern("bearish_engulfing", "two_candle", "bearish", 0.82, previous, current, "Current bearish candle fully engulfs previous bullish candle body."))
        if previous["is_bearish"] and previous["body_ratio"] >= 0.50 and not current["is_bearish"] and self._body_inside(current, previous):
            patterns.append(self._pattern("bullish_harami", "two_candle", "bullish", 0.70, previous, current, "Current bullish or neutral body is inside previous bearish body."))
        if previous["is_bullish"] and previous["body_ratio"] >= 0.50 and not current["is_bullish"] and self._body_inside(current, previous):
            patterns.append(self._pattern("bearish_harami", "two_candle", "bearish", 0.70, previous, current, "Current bearish or neutral body is inside previous bullish body."))
        if previous["is_bearish"] and current["is_bullish"] and current["open"] < min(previous["low"], previous["close"]) and previous_midpoint < current["close"] < previous["open"]:
            patterns.append(self._pattern("piercing_line", "two_candle", "bullish", 0.76, previous, current, "Bullish candle opens below the prior selloff and closes above the previous body midpoint."))
        if previous["is_bullish"] and current["is_bearish"] and current["open"] > max(previous["high"], previous["close"]) and previous_midpoint > current["close"] > previous["open"]:
            patterns.append(self._pattern("dark_cloud_cover", "two_candle", "bearish", 0.76, previous, current, "Bearish candle opens above the prior advance and closes below the previous body midpoint."))
        if abs(previous["high"] - current["high"]) <= tolerance and not previous["is_bearish"] and not current["is_bullish"]:
            patterns.append(self._pattern("tweezer_top", "two_candle", "bearish", 0.66, previous, current, "Two candles form similar highs with bearish pressure on the second candle."))
        if abs(previous["low"] - current["low"]) <= tolerance and not previous["is_bullish"] and not current["is_bearish"]:
            patterns.append(self._pattern("tweezer_bottom", "two_candle", "bullish", 0.66, previous, current, "Two candles form similar lows with bullish pressure on the second candle."))

        return patterns

    def _detect_three_candle_patterns(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(candles) < 3:
            return []

        first, second, third = candles[-3], candles[-2], candles[-1]
        patterns: list[dict[str, Any]] = []
        first_midpoint = (first["open"] + first["close"]) / 2

        if first["is_bearish"] and first["body_ratio"] >= 0.50 and second["body_ratio"] <= 0.35 and third["is_bullish"] and third["close"] > first_midpoint:
            patterns.append(self._pattern("morning_star", "three_candle", "bullish", 0.78, first, third, "Bearish candle, indecision candle, and bullish close above the first body midpoint."))
        if first["is_bullish"] and first["body_ratio"] >= 0.50 and second["body_ratio"] <= 0.35 and third["is_bearish"] and third["close"] < first_midpoint:
            patterns.append(self._pattern("evening_star", "three_candle", "bearish", 0.78, first, third, "Bullish candle, indecision candle, and bearish close below the first body midpoint."))
        if all(candle["is_bullish"] and candle["body_ratio"] > 0.20 for candle in [first, second, third]) and first["close"] < second["close"] < third["close"]:
            patterns.append(self._pattern("three_white_soldiers", "three_candle", "bullish", 0.82, first, third, "Three meaningful bullish bodies close successively higher."))
        if all(candle["is_bearish"] and candle["body_ratio"] > 0.20 for candle in [first, second, third]) and first["close"] > second["close"] > third["close"]:
            patterns.append(self._pattern("three_black_crows", "three_candle", "bearish", 0.82, first, third, "Three meaningful bearish bodies close successively lower."))

        return patterns

    def _detect_continuation_patterns(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(candles) < 2:
            return []

        previous, current = candles[-2], candles[-1]
        patterns: list[dict[str, Any]] = []
        strong_body = current["body_ratio"] >= 0.60

        if current["high"] < previous["high"] and current["low"] > previous["low"]:
            patterns.append(self._pattern("inside_bar", "continuation_indecision", "neutral", 0.68, previous, current, "Current range is fully inside the previous candle range."))
        if current["high"] > previous["high"] and current["low"] < previous["low"]:
            patterns.append(self._pattern("outside_bar", "continuation_indecision", "neutral", 0.68, previous, current, "Current range fully exceeds the previous candle range."))
        if previous["is_bearish"] and current["is_bullish"] and (current["open"] > previous["open"] or strong_body):
            patterns.append(self._pattern("bullish_kicker", "continuation_indecision", "bullish", 0.74, previous, current, "Previous bearish candle is followed by a strong bullish displacement."))
        if previous["is_bullish"] and current["is_bearish"] and (current["open"] < previous["open"] or strong_body):
            patterns.append(self._pattern("bearish_kicker", "continuation_indecision", "bearish", 0.74, previous, current, "Previous bullish candle is followed by a strong bearish displacement."))

        return patterns

    def _detect_chart_patterns(self, candles: list[dict[str, Any]], math_result: dict[str, Any]) -> list[dict[str, Any]]:
        if len(candles) < 20:
            return []

        recent = candles[-80:]
        swings = self._swing_points(recent)
        patterns: list[dict[str, Any]] = []

        head_and_shoulders = self._head_and_shoulders(swings, inverse=False)
        if head_and_shoulders:
            start, end, confirmed = head_and_shoulders
            confidence = 0.66 if confirmed else 0.52
            patterns.append(self._pattern("head_and_shoulders", "chart_pattern", "bearish", confidence, start, end, "Recent swing highs form shoulders around a higher head; confidence is lower without neckline break."))

        inverse_head_and_shoulders = self._head_and_shoulders(swings, inverse=True)
        if inverse_head_and_shoulders:
            start, end, confirmed = inverse_head_and_shoulders
            confidence = 0.66 if confirmed else 0.52
            patterns.append(self._pattern("inverse_head_and_shoulders", "chart_pattern", "bullish", confidence, start, end, "Recent swing lows form shoulders around a lower head; confidence is lower without neckline breakout."))

        bullish_pennant = self._pennant(recent, bullish=True)
        if bullish_pennant:
            start, end, confirmed = bullish_pennant
            confidence = 0.64 if confirmed else 0.50
            patterns.append(self._pattern("bullish_pennant", "chart_pattern", "bullish", confidence, start, end, "Strong upward impulse followed by volatility compression."))

        bearish_pennant = self._pennant(recent, bullish=False)
        if bearish_pennant:
            start, end, confirmed = bearish_pennant
            confidence = 0.64 if confirmed else 0.50
            patterns.append(self._pattern("bearish_pennant", "chart_pattern", "bearish", confidence, start, end, "Strong downward impulse followed by volatility compression."))

        return patterns

    def _swing_points(self, candles: list[dict[str, Any]], lookback: int = 2) -> list[dict[str, Any]]:
        swings: list[dict[str, Any]] = []
        for index in range(lookback, len(candles) - lookback):
            window = candles[index - lookback : index + lookback + 1]
            candle = candles[index]
            if candle["high"] == max(item["high"] for item in window):
                swings.append({"type": "high", "candle": candle, "value": candle["high"]})
            if candle["low"] == min(item["low"] for item in window):
                swings.append({"type": "low", "candle": candle, "value": candle["low"]})
        return swings[-12:]

    def _head_and_shoulders(self, swings: list[dict[str, Any]], inverse: bool) -> tuple[dict[str, Any], dict[str, Any], bool] | None:
        expected = ["low", "high", "low", "high", "low", "high", "low"] if inverse else ["high", "low", "high", "low", "high", "low", "high"]
        for offset in range(max(len(swings) - 5, 0), -1, -1):
            segment = swings[offset : offset + 5]
            if len(segment) < 5 or [point["type"] for point in segment] != expected:
                continue

            left, neckline_a, head, neckline_b, right = segment
            shoulder_base     = max(abs(left["value"]), abs(right["value"]), 1.0)
            shoulders_similar = abs(left["value"] - right["value"]) / shoulder_base <= 0.08
            if inverse:
                head_extreme = head["value"] < left["value"] * 0.97 and head["value"] < right["value"] * 0.97
                neckline = max(neckline_a["value"], neckline_b["value"])
                confirmed = right["candle"]["close"] > neckline
            else:
                head_extreme = head["value"] > left["value"] * 1.03 and head["value"] > right["value"] * 1.03
                neckline = min(neckline_a["value"], neckline_b["value"])
                confirmed = right["candle"]["close"] < neckline
            if shoulders_similar and head_extreme:
                return left["candle"], right["candle"], confirmed
        return None

    def _pennant(self, candles: list[dict[str, Any]], bullish: bool) -> tuple[dict[str, Any], dict[str, Any], bool] | None:
        if len(candles) < 16:
            return None

        recent = candles[-16:]
        pole = recent[:6]
        consolidation = recent[6:]
        pole_change = (pole[-1]["close"] - pole[0]["close"]) / max(abs(pole[0]["close"]), 1.0)
        if bullish and pole_change < 0.02:
            return None
        if not bullish and pole_change > -0.02:
            return None

        highs = [candle["high"] for candle in consolidation]
        lows = [candle["low"] for candle in consolidation]
        high_slope = self._slope(highs)
        low_slope = self._slope(lows)
        range_start = highs[0] - lows[0]
        range_end = highs[-1] - lows[-1]
        contracting = range_start > 0 and range_end < range_start * 0.75
        if not (contracting and high_slope < 0 and low_slope > 0):
            return None

        confirmed = consolidation[-1]["close"] > highs[-2] if bullish else consolidation[-1]["close"] < lows[-2]
        return pole[0], consolidation[-1], confirmed

    @staticmethod
    def _pattern(name: str, category: str, direction: str, confidence: float, start: dict[str, Any], end: dict[str, Any], reason: str) -> dict[str, Any]:
        return {
            "name": name,
            "category": category,
            "direction": direction,
            "confidence": max(0.0, min(1.0, confidence)),
            "start_index": start.get("index"),
            "end_index": end.get("index"),
            "timestamp": end.get("timestamp"),
            "reason": reason}

    @staticmethod
    def _body_inside(current: dict[str, Any], previous: dict[str, Any]) -> bool:
        current_min, current_max = sorted([current["open"], current["close"]])
        previous_min, previous_max = sorted([previous["open"], previous["close"]])
        return current_min >= previous_min and current_max <= previous_max

    @staticmethod
    def _recent_trend(candles: list[dict[str, Any]], lookback: int = 5) -> str:
        recent = candles[-lookback - 1 :]
        if len(recent) < 2:
            return "flat"
        change = recent[-1]["close"] - recent[0]["close"]
        if change > 0:
            return "up"
        if change < 0:
            return "down"
        return "flat"

    @staticmethod
    def _slope(values: list[float]) -> float:
        if len(values) < 2:
            return 0.0
        return (values[-1] - values[0]) / (len(values) - 1)

    @staticmethod
    def _has_direction(patterns: list[dict[str, Any]], direction: str) -> bool:
        return any(pattern.get("direction") == direction for pattern in patterns)

    @staticmethod
    def _pattern_summary(patterns: list[dict[str, Any]]) -> dict[str, Any]:
        active_categories = sorted({pattern["category"] for pattern in patterns})
        return {
            "total_patterns": len(patterns),
            "bullish_count": sum(1 for pattern in patterns if pattern.get("direction") == "bullish"),
            "bearish_count": sum(1 for pattern in patterns if pattern.get("direction") == "bearish"),
            "neutral_count": sum(1 for pattern in patterns if pattern.get("direction") == "neutral"),
            "high_confidence_count": sum(1 for pattern in patterns if pattern.get("confidence", 0) >= 0.75),
            "active_categories": active_categories,
        }

    @staticmethod
    def _detect_statistical_regimes(math_result: dict[str, Any]) -> list[str]:
        stat_last = math_result.get("statistics", {}).get("last", {})
        regime_flags = math_result.get("statistical_regimes", {}).get("regime_flags", {})
        statistical_regimes = []

        zscore = CandlestickPatternDetector._first_stat_value(stat_last, "rolling_zscore")
        kurtosis = CandlestickPatternDetector._first_stat_value(stat_last, "returns_rolling_kurtosis")
        skewness = CandlestickPatternDetector._first_stat_value(stat_last, "returns_rolling_skewness")
        volatility = CandlestickPatternDetector._first_stat_value(stat_last, "returns_rolling_std")

        if zscore is not None and abs(zscore) >= 2:
            statistical_regimes.append("mean_reversion_extreme")
        if kurtosis is not None and kurtosis >= 3:
            statistical_regimes.append("fat_tail_regime")
        if skewness is not None and skewness <= -1:
            statistical_regimes.append("negative_skew_risk")
        if skewness is not None and skewness >= 1:
            statistical_regimes.append("positive_skew_pressure")
        if volatility is not None and volatility > 0:
            statistical_regimes.append("volatility_active")
        if regime_flags.get("high_volatility_regime"):
            statistical_regimes.append("high_volatility_regime")
        if regime_flags.get("fat_tail_risk"):
            statistical_regimes.append("fat_tail_risk")

        return statistical_regimes

    @staticmethod
    def _first_stat_value(stat_last: dict[str, Any], metric: str) -> Any:
        for window in OFFICIAL_STAT_WINDOWS:
            candidate_keys = [
                f"close__{metric}_{window}",
                f"{metric}_{window}",
                f"close_{metric}_{window}",
            ]
            for key in candidate_keys:
                value = stat_last.get(key)
                if value is not None:
                    return value
        return None

    @staticmethod
    def _build_pattern_inputs(math_result: dict[str, Any], view_math: dict[str, Any]) -> dict[str, Any]:
        technical_last = math_result.get("technical_indicators", {}).get("last", {})
        derived_technical = view_math.get("candlestick_derived", {}).get("technical_indicators", {}).get("last", {})
        regime_flags = math_result.get("statistical_regimes", {}).get("regime_flags", {})
        return {
            "uses_technical_indicators": bool(technical_last or derived_technical),
            "uses_statistics": bool(math_result.get("statistics")),
            "uses_statistical_regimes": bool(math_result.get("statistical_regimes")),
            "uses_regime_flags": bool(regime_flags),
            "uses_microstructure": False,
            "technical_indicators": sorted(technical_last.keys()),
            "derived_technical_indicators": sorted(derived_technical.keys()),
            "regime_flags": regime_flags,
        }

    @staticmethod
    def _float(value: Any) -> float | None:
        """Convert scalar-like values to float.

        Returns None for missing, invalid, or non-scalar values.
        This prevents pandas/numpy arrays from reaching pd.isna as arrays.
        """
        if value is None:
            return None

        if hasattr(value, "tolist") and not isinstance(value, (str, bytes)):
            value = value.tolist()

        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                return None
            value = value[0]

        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None

        try:
            if pd.isna(parsed):
                return None
        except (TypeError, ValueError):
            return None

        return float(parsed)
