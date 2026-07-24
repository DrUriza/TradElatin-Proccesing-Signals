from __future__ import annotations

from processing_signals.processing.math.technical_cross_signals import (
    attach_ma_crosses_to_ohlc,
    detect_series_crosses,
    detect_zero_crosses,
)


def _candles() -> list[dict]:
    return [
        {"timestamp": 100, "open": 10, "high": 12, "low": 9, "close": 11, "is_closed": True},
        {"timestamp": 200, "open": 11, "high": 13, "low": 10, "close": 12, "is_closed": True},
        {"timestamp": 300, "open": 12, "high": 14, "low": 11, "close": 13, "is_closed": True},
    ]


def test_bullish_cross_adds_exactly_one_event() -> None:
    out = attach_ma_crosses_to_ohlc(
        _candles(),
        {
            "ma_7": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 12}],
            "ma_25": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 11}],
            "atr_14": [{"timestamp": 200, "value": 2}],
        },
        [("ma_7", "ma_25")],
    )

    assert out[1]["ma_crosses"][0]["direction"] == "bullish"
    assert out[1]["ma_crosses"][0]["marker"] == "arrow_up"
    assert out[1]["ma_crosses"][0]["marker_price"] < out[1]["low"]
    assert sum(len(candle["ma_crosses"]) for candle in out) == 1


def test_bearish_cross_adds_exactly_one_event() -> None:
    out = attach_ma_crosses_to_ohlc(
        _candles(),
        {
            "ma_7": [{"timestamp": 100, "value": 12}, {"timestamp": 200, "value": 10}],
            "ma_25": [{"timestamp": 100, "value": 12}, {"timestamp": 200, "value": 11}],
        },
        [("ma_7", "ma_25")],
    )

    event = out[1]["ma_crosses"][0]
    assert event["direction"] == "bearish"
    assert event["marker"] == "arrow_down"
    assert event["marker_price"] > out[1]["high"]
    assert event["quality_flags"] == ["marker_offset_without_atr"]


def test_no_cross_still_adds_empty_lists() -> None:
    out = attach_ma_crosses_to_ohlc(
        _candles(),
        {
            "ma_7": [{"timestamp": 100, "value": 12}, {"timestamp": 200, "value": 13}],
            "ma_25": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 11}],
        },
        [("ma_7", "ma_25")],
    )

    assert [candle["ma_crosses"] for candle in out] == [[], [], []]


def test_multiple_crosses_on_same_candle_are_preserved() -> None:
    out = attach_ma_crosses_to_ohlc(
        _candles(),
        {
            "ma_7": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 12}],
            "ma_25": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 11}],
            "ema_9": [{"timestamp": 100, "value": 9}, {"timestamp": 200, "value": 13}],
            "ema_21": [{"timestamp": 100, "value": 9}, {"timestamp": 200, "value": 12}],
        },
        [("ma_7", "ma_25"), ("ema_9", "ema_21")],
    )

    assert len(out[1]["ma_crosses"]) == 2
    assert {event["pair"] for event in out[1]["ma_crosses"]} == {"ma_7_x_ma_25", "ema_9_x_ema_21"}


def test_missing_timestamp_alignment_does_not_add_event() -> None:
    out = attach_ma_crosses_to_ohlc(
        _candles(),
        {
            "ma_7": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 12}],
            "ma_25": [{"timestamp": 100, "value": 10}, {"timestamp": 300, "value": 11}],
        },
        [("ma_7", "ma_25")],
    )

    assert sum(len(candle["ma_crosses"]) for candle in out) == 0


def test_partial_candle_does_not_generate_cross() -> None:
    candles = _candles()
    candles[1]["is_closed"] = False
    out = attach_ma_crosses_to_ohlc(
        candles,
        {
            "ma_7": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 12}],
            "ma_25": [{"timestamp": 100, "value": 10}, {"timestamp": 200, "value": 11}],
        },
        [("ma_7", "ma_25")],
    )

    assert out[1]["ma_crosses"] == []


def test_detect_series_crosses_returns_deterministic_events() -> None:
    events = detect_series_crosses(
        [{"timestamp": 100, "value": 1}, {"timestamp": 200, "value": 3}, {"timestamp": 300, "value": 1}],
        [{"timestamp": 100, "value": 2}, {"timestamp": 200, "value": 2}, {"timestamp": 300, "value": 2}],
        event_type="oi_ma_cross",
        id_prefix="sma20_x_sma50",
        fast_series_name="sma20",
        slow_series_name="sma50",
    )

    assert [event["id"] for event in events] == ["sma20_x_sma50_200_bullish", "sma20_x_sma50_300_bearish"]
    assert events[0]["marker"] == "arrow_up"
    assert events[1]["marker"] == "arrow_down"


def test_detect_zero_crosses_marks_regime_changes_as_neutral() -> None:
    events = detect_zero_crosses(
        [{"timestamp": 100, "value": -0.1}, {"timestamp": 200, "value": 0.1}, {"timestamp": 300, "value": -0.2}],
        event_type="funding_zero_cross",
        id_prefix="funding_zero_cross",
        positive_event="funding_positive",
        negative_event="funding_negative",
        event_field="funding_regime",
        anchor_series="funding_rate",
        value_field="funding_rate_value",
    )

    assert [event["id"] for event in events] == [
        "funding_zero_cross_200_funding_positive",
        "funding_zero_cross_300_funding_negative",
    ]
    assert {event["direction"] for event in events} == {"neutral"}
    assert {event["marker"] for event in events} == {"diamond"}
