from __future__ import annotations

import pandas as pd

from processing_signals.processing.math.technical_cross_signals import detect_indicator_crosses


def test_stochastic_bullish_cross_only_in_oversold_zone() -> None:
    events = detect_indicator_crosses(
        _source(),
        pd.DataFrame({"stoch_k_14": [18.0, 19.0], "stoch_d_14": [19.0, 18.0]}),
    )

    assert [event["id"] for event in events["stochastic"]] == ["stochastic_cross_300_bullish"]
    assert events["stochastic"][0]["zone"] == "oversold"
    assert events["stochastic"][0]["marker"] == "arrow_up"


def test_stochastic_bearish_cross_only_in_overbought_zone() -> None:
    events = detect_indicator_crosses(
        _source(),
        pd.DataFrame({"stoch_k_14": [82.0, 81.0], "stoch_d_14": [81.0, 82.0]}),
    )

    assert [event["id"] for event in events["stochastic"]] == ["stochastic_cross_300_bearish"]
    assert events["stochastic"][0]["zone"] == "overbought"
    assert events["stochastic"][0]["marker"] == "arrow_down"


def test_stochastic_middle_zone_and_partial_bar_do_not_emit() -> None:
    middle = detect_indicator_crosses(
        _source(),
        pd.DataFrame({"stoch_k_14": [45.0, 55.0], "stoch_d_14": [55.0, 45.0]}),
    )
    partial = detect_indicator_crosses(
        _source(partial_last=True),
        pd.DataFrame({"stoch_k_14": [18.0, 19.0], "stoch_d_14": [19.0, 18.0]}),
    )

    assert middle["stochastic"] == []
    assert partial["stochastic"] == []


def test_stochastic_threshold_edges_are_valid() -> None:
    bullish = detect_indicator_crosses(
        _source(),
        pd.DataFrame({"stoch_k_14": [19.0, 20.0], "stoch_d_14": [20.0, 19.0]}),
    )
    bearish = detect_indicator_crosses(
        _source(),
        pd.DataFrame({"stoch_k_14": [81.0, 80.0], "stoch_d_14": [80.0, 81.0]}),
    )

    assert len(bullish["stochastic"]) == 1
    assert len(bearish["stochastic"]) == 1


def test_macd_signal_crosses_and_histogram_context() -> None:
    events = detect_indicator_crosses(
        _source(count=4),
        pd.DataFrame(
            {
                "macd": [-2.0, -1.0, 2.0, 1.0],
                "macd_signal": [-1.0, -1.5, 1.0, 2.0],
                "macd_hist": [-1.0, 0.5, 1.0, -1.0],
            }
        ),
    )

    assert [event["id"] for event in events["macd"]] == [
        "macd_signal_cross_300_bullish",
        "macd_signal_cross_900_bearish",
    ]
    assert events["macd"][0]["histogram_value"] == 0.5
    assert events["macd"][0]["zero_zone"] == "below_zero"
    assert events["macd"][1]["zero_zone"] == "above_zero"


def test_macd_does_not_repeat_or_emit_on_partial_bar() -> None:
    repeated = detect_indicator_crosses(
        _source(count=3),
        pd.DataFrame({"macd": [1.0, 2.0, 3.0], "macd_signal": [0.0, 1.0, 2.0], "macd_hist": [1.0, 1.0, 1.0]}),
    )
    partial = detect_indicator_crosses(
        _source(partial_last=True),
        pd.DataFrame({"macd": [-1.0, 1.0], "macd_signal": [1.0, -1.0], "macd_hist": [-2.0, 2.0]}),
    )

    assert repeated["macd"] == []
    assert partial["macd"] == []


def test_adx_di_crosses_and_strength_threshold_crosses() -> None:
    events = detect_indicator_crosses(
        _source(count=4),
        pd.DataFrame(
            {
                "adx_14": [24.0, 25.0, 26.0, 24.0],
                "plus_di_14": [10.0, 20.0, 18.0, 12.0],
                "minus_di_14": [20.0, 10.0, 12.0, 18.0],
            }
        ),
    )

    assert [event["id"] for event in events["adx"]] == [
        "adx_threshold_cross_300_strength_on",
        "di_cross_300_bullish",
        "adx_threshold_cross_900_strength_off",
        "di_cross_900_bearish",
    ]
    bullish  = [event for event in events["adx"] if event["event_type"] == "di_cross"][0]
    bearish  = [event for event in events["adx"] if event["event_type"] == "di_cross"][1]
    strength = [event for event in events["adx"] if event["event_type"] == "adx_threshold_cross"][0]
    assert bullish["strength_confirmed"] is True
    assert bearish["strength_confirmed"] is False
    assert strength["direction"] == "neutral"
    assert strength["marker"] == "diamond"


def test_adx_partial_bar_does_not_emit() -> None:
    events = detect_indicator_crosses(
        _source(partial_last=True),
        pd.DataFrame({"adx_14": [24.0, 25.0], "plus_di_14": [10.0, 20.0], "minus_di_14": [20.0, 10.0]}),
    )

    assert events["adx"] == []


def _source(*, count: int = 2, partial_last: bool = False) -> pd.DataFrame:
    rows = []
    for index in range(count):
        rows.append(
            {
                "timestamp": index * 300,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "is_closed": not (partial_last and index == count - 1),
                "is_partial": partial_last and index == count - 1,
            }
        )
    return pd.DataFrame(rows)
