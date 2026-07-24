from __future__ import annotations

from copy import deepcopy

import pytest

from processing_signals.classification.prices_ohlcv.prices_ohlcv_classifier import (
    calculate_group_bias, calculate_market_biases, calculate_overall_bias, calculate_timeframe_bias,
    classify_adx, classify_atr, classify_basis, classify_candlestick_patterns, classify_kurtosis,
    classify_market_agreement, classify_market_leadership, classify_max_drawdown, classify_mfi,
    classify_profit_factor, classify_rsi, classify_sharpe, classify_statistical_performance,
    classify_technical_crosses, classify_williams_r, classify_win_rate, evaluate_prices_classification_quality,
    run_prices_ohlcv_classification,
)


TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
MARKETS    = ("general", "spot", "futures")


def _indicator_package(sign: float = 1.0) -> dict:
    return {
        "rsi": {"current": {"rsi": 60.0}},
        "macd": {"current": {"macd": sign * 2, "signal": sign, "histogram": sign}},
        "stochastic": {"current": {"k": 60.0, "d": 50.0}},
        "adx": {"current": {"adx": 30.0, "di_plus": 25.0 if sign > 0 else 15.0, "di_minus": 15.0 if sign > 0 else 25.0}},
        "cci": {"current": {"cci": sign * 120}}, "mfi": {"current": {"mfi": 74.0}},
        "williams_r": {"current": {"williams_r": -50.0}}, "atr": {"current": {"atr": 2.0}},
        "tsi": {"current": {"tsi": sign * 10}, "parameters": {"slow_period": 25, "fast_period": 13}},
    }


def _bias_values(sign: float = 1.0) -> dict:
    return {"values": {
        "ema_9_minus_ema_21": sign, "ema_21_minus_ema_50": sign, "sma_20_minus_sma_50": sign,
        "macd_minus_signal": sign, "macd_histogram": sign, "rsi_centered": sign * 10,
        "stochastic_k_minus_d": sign, "adx": 30, "di_plus_minus_di_minus": sign,
        "cci": sign * 120, "mfi_centered": sign * 15, "williams_r_centered": sign * 15,
        "tsi": sign * 10, "close_minus_bollinger_middle": sign, "atr_percent_of_close": 1.0,
    }}


def _statistics() -> dict:
    return {"descriptive": {"mean_close": 100, "return_standard_deviation": 0.01, "skewness": 0.1, "kurtosis": 2.15,
                            "z_score": 0.5, "metadata": {"kurtosis_mode": "pearson"}},
            "risk": {"var_95_return": -0.03, "cvar_95_return": -0.04, "var_95_price": -3, "cvar_95_price": -4},
            "performance": {"max_consecutive_wins": 8, "max_consecutive_losses": 4, "omega_ratio": 1.42,
                            "sharpe_ratio": 1.85, "sortino_ratio": 2.42, "calmar_ratio": 1.67,
                            "max_drawdown": -0.0482, "profit_factor": 2.15, "recovery_factor": 3.74,
                            "win_rate": 0.583, "performance_basis": "market_returns",
                            "metadata": {"periods_per_year": 8760, "return_type": "simple"}}}


def make_processing_output() -> dict:
    indicators = {market: {tf: _indicator_package(-1 if market == "futures" else 1) for tf in TIMEFRAMES} for market in MARKETS}
    biases     = {market: {"timeframes": {tf: _bias_values(-1 if market == "futures" else 1) for tf in TIMEFRAMES}} for market in MARKETS}
    statistics = {market: {tf: _statistics() for tf in TIMEFRAMES} for market in MARKETS}
    crosses    = {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS}
    patterns   = {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS}
    crosses["general"]["1h"] = [{"timestamp": 1, "cross_id": "ema_9_above_ema_21", "direction": 1}]
    patterns["general"]["1h"] = [{"timestamp": 1, "pattern_id": "hammer", "direction": 1, "confidence": 0.82}]
    records = [{"timestamp": 1, "open": 99, "high": 102, "low": 98, "close": 101, "volume_usd": 1}]
    main    = {market: {"timeframes": {tf: {"records": deepcopy(records), "unavailable_records": []} for tf in TIMEFRAMES}} for market in MARKETS}
    return {"family": "prices_ohlcv", "stage": "processing", "mode": "bootstrap", "markets": {},
            "features": {"market_selector": {"default_market": "general", "available_markets": list(MARKETS), "timeframes": list(TIMEFRAMES)},
                         "main_ohlcv": main, "indicators": indicators, "bias_components": biases,
                         "statistical_performance": {"markets": statistics}, "technical_crosses": crosses,
                         "candlestick_patterns": patterns,
                         "spot_futures_comparison": {"by_timeframe": {tf: {"current": {"basis_usd": 1, "basis_percent": 0.1}, "series": []} for tf in TIMEFRAMES}}},
            "quality": {"status": "ok", "warnings": [], "errors": []}}


def test_indicator_threshold_classifications():
    assert classify_rsi(50)["state"] == "neutral"
    assert classify_rsi(72)["state"] == "overbought"
    assert classify_rsi(28)["state"] == "oversold"
    assert classify_mfi(74)["signal"] == "neutral"
    assert classify_williams_r(-50)["state"] == "neutral"
    assert classify_atr(100, 2.0)["state"] == "high"


def test_adx_keeps_strength_and_direction_separate():
    result = classify_adx(30, 25, 15)
    assert result["state"] == "strong" and result["signal"] == "neutral" and result["direction"] == "bullish"


def test_statistical_thresholds():
    assert classify_kurtosis(2.15, "pearson")["state"] == "platykurtic"
    assert classify_max_drawdown(-0.0482)["state"] == "low"
    assert classify_profit_factor(2.15)["state"] == "strong"
    assert classify_win_rate(0.583)["state"] == "good"


def test_bias_scores_groups_and_micro_confirmation():
    positive = calculate_timeframe_bias(_bias_values(1), "5m")
    negative = calculate_timeframe_bias(_bias_values(-1), "5m")
    neutral  = calculate_timeframe_bias({"values": {name: 0 for name in _bias_values()["values"]}}, "5m")
    assert positive["label"] in {"bullish", "strong_bullish"}
    assert negative["label"] in {"bearish", "strong_bearish"}
    assert neutral["label"] == "neutral"
    tf = {"5m": positive, "15m": positive, "1h": positive, "4h": positive, "1d": positive}
    assert calculate_group_bias(tf, {"5m": 0.4, "15m": 0.6})["timeframes_used"] == ["5m", "15m"]
    groups = {"short": calculate_group_bias(tf, {"5m": 0.4, "15m": 0.6}),
              "mid": calculate_group_bias(tf, {"1h": 0.4, "4h": 0.6}), "long": calculate_group_bias(tf, {"1d": 1})}
    aligned      = calculate_overall_bias(groups, positive)
    contradicted = calculate_overall_bias(groups, negative)
    assert aligned["score"] == contradicted["score"]
    assert aligned["confidence"] > contradicted["confidence"]


def test_market_relationship_rules():
    assert classify_basis({"basis_percent": 0.1})["state"] == "premium"
    assert classify_basis({"basis_percent": -0.1})["state"] == "discount"
    biases = {"general": {"overall": {"label": "bullish", "score": 0.5}},
              "spot": {"overall": {"label": "bullish", "score": -0.5}},
              "futures": {"overall": {"label": "bearish", "score": 0.5}}}
    assert classify_market_agreement(biases)["state"] == "spot_confirmed_futures_divergent"
    assert classify_market_leadership(biases)["state"] == "derivatives_led"
    biases["spot"]["overall"]["score"], biases["futures"]["overall"]["score"] = 0.6, -0.4
    assert classify_market_leadership(biases)["state"] == "spot_led"


def test_market_agreement_specific_precedence_and_generic_divergence():
    def biases(general, spot, futures):
        return {"general": {"overall": {"label": general}}, "spot": {"overall": {"label": spot}},
                "futures": {"overall": {"label": futures}}}
    assert classify_market_agreement(biases("bullish", "bullish", "bearish"))["state"] == "spot_confirmed_futures_divergent"
    assert classify_market_agreement(biases("bearish", "bullish", "bearish"))["state"] == "futures_confirmed_spot_divergent"
    assert classify_market_agreement(biases("neutral", "bullish", "bearish"))["state"] == "divergent"
    assert classify_market_agreement(biases("bullish", "strong_bullish", "bullish"))["state"] == "confirmed"


def test_missing_descriptive_values_are_unavailable_and_standard_deviations_keep_units():
    package = _statistics()
    package["descriptive"].update({"mean_close": None, "close_standard_deviation": None, "return_standard_deviation": None})
    package["performance"].update({"max_consecutive_wins": None, "max_consecutive_losses": None})
    result = classify_statistical_performance(package, "1h")
    assert result["mean"]["state"] == "unavailable"
    assert result["standard_deviation"]["state"] == "unavailable"
    assert result["max_consecutive_wins"]["state"] == "unavailable"
    assert result["max_consecutive_losses"]["state"] == "unavailable"
    package["descriptive"].update({"close_standard_deviation": 175.0, "return_standard_deviation": 0.025})
    result = classify_statistical_performance(package, "1h")["standard_deviation"]
    assert result["value"] == 175.0 and result["return_value"] == 0.025
    assert result["state"] == "high"
    assert result["metadata"]["display_basis"] == "close"


def test_threshold_confidence_varies_and_exact_boundaries_are_half():
    assert classify_sharpe(1.0)["confidence"] == 0.50
    assert classify_sharpe(1.0)["confidence"] != classify_sharpe(1.9)["confidence"]
    assert classify_profit_factor(2.0)["confidence"] == 0.50
    assert classify_profit_factor(2.0)["confidence"] != classify_profit_factor(4.0)["confidence"]


def test_events_are_semantic_without_recalculation():
    crosses = {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS}
    crosses["general"]["1h"] = [{"timestamp": 1, "cross_id": "ema_9_above_ema_21", "direction": 1,
                                   "first_series": "ema_9", "second_series": "ema_21", "previous_difference": -1.0, "current_difference": 2.0},
                                  {"timestamp": 2, "cross_id": "ema_9_below_ema_21", "direction": -1}]
    output = classify_technical_crosses(crosses)["general"]["1h"]
    assert output[0]["marker"] == "arrow_up" and output[1]["marker"] == "arrow_down"
    assert output[0]["calculation"] == {"first_series": "ema_9", "second_series": "ema_21", "previous_difference": -1.0,
                                         "current_difference": 2.0, "raw_direction": 1}
    patterns = {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS}
    patterns["general"]["1h"] = [{"timestamp": 1, "pattern_id": "hammer", "direction": 1, "confidence": 0.8,
                                    "components": {"body_ratio": 0.4, "invalid": float("nan")}}]
    event = classify_candlestick_patterns(patterns)["general"]["1h"][0]
    assert event["signal"] == "bullish" and event["confidence_level"] == "high"
    assert event["calculation"]["components"] == {"body_ratio": 0.4, "invalid": None}


def test_quality_detects_missing_structure_but_accepts_unavailable_and_empty_events():
    processing = make_processing_output()
    output     = run_prices_ohlcv_classification(processing)
    assert output["quality"]["status"] == "ok"
    empty_events = {"technical_crosses": {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS},
                    "candlestick_patterns": {market: {tf: [] for tf in TIMEFRAMES} for market in MARKETS}}
    quality = evaluate_prices_classification_quality(processing_features=processing["features"],
                                                     indicator_signals=output["indicator_signals"], statistical_signals=output["statistical_signals"],
                                                     technical_bias=output["technical_bias"], market_relationship=output["market_relationship"], events=empty_events)
    assert quality["status"] == "ok"
    missing_market = deepcopy(output["indicator_signals"])
    del missing_market["spot"]
    quality = evaluate_prices_classification_quality(processing_features=processing["features"], indicator_signals=missing_market,
                                                     statistical_signals=output["statistical_signals"], technical_bias=output["technical_bias"],
                                                     market_relationship=output["market_relationship"], events=empty_events)
    assert quality["status"] == "invalid" and "market.spot" in quality["errors"]
    missing_indicator = deepcopy(output["indicator_signals"])
    del missing_indicator["general"]["1h"]["rsi"]
    quality = evaluate_prices_classification_quality(processing_features=processing["features"], indicator_signals=missing_indicator,
                                                     statistical_signals=output["statistical_signals"], technical_bias=output["technical_bias"],
                                                     market_relationship=output["market_relationship"], events=empty_events)
    assert any(field.endswith(".rsi") for field in quality["missing_fields"])
    unavailable = deepcopy(output["indicator_signals"])
    unavailable["general"]["1h"]["rsi"]["state"] = "unavailable"
    quality = evaluate_prices_classification_quality(processing_features=processing["features"], indicator_signals=unavailable,
                                                     statistical_signals=output["statistical_signals"], technical_bias=output["technical_bias"],
                                                     market_relationship=output["market_relationship"], events=empty_events)
    assert not any(field.endswith(".rsi") for field in quality["missing_fields"])


def test_quality_detects_timeframe_performance_basis_and_tsi_parameters():
    processing   = make_processing_output()
    output       = run_prices_ohlcv_classification(processing)
    empty_events = {"technical_crosses": {}, "candlestick_patterns": {}}
    indicators   = deepcopy(output["indicator_signals"])
    statistics   = deepcopy(output["statistical_signals"])
    del indicators["general"]["1m"]
    statistics["general"]["1h"]["metadata"]["performance_basis"] = None
    indicators["spot"]["1h"]["tsi"]["parameters"] = {"slow_period": 14, "fast_period": 7}
    quality = evaluate_prices_classification_quality(processing_features=processing["features"], indicator_signals=indicators,
                                                     statistical_signals=statistics, technical_bias=output["technical_bias"],
                                                     market_relationship=output["market_relationship"], events=empty_events)
    assert "indicator_signals.general.1m" in quality["errors"]
    assert any("performance_basis" in field for field in quality["missing_fields"])
    assert any("tsi.parameters" in field for field in quality["missing_fields"])


def test_public_classifier_covers_all_markets_and_preserves_performance_basis():
    output = run_prices_ohlcv_classification(make_processing_output())
    assert set(output["technical_bias"]) == set(MARKETS)
    assert output["statistical_signals"]["general"]["1h"]["metadata"]["performance_basis"] == "market_returns"
    assert output["indicator_signals"]["general"]["1h"]["tsi"]["parameters"] == {"slow_period": 25, "fast_period": 13}
