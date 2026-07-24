from copy import deepcopy

from processing_signals.processing.math.patterns import detect_candlestick_patterns


def _row(timestamp, opened, high, low, close):
    return {"timestamp": timestamp, "open": opened, "high": high, "low": low, "close": close, "volume_usd": 1.0}


def test_detects_controlled_bullish_and_bearish_engulfing_without_mutation_or_labels():
    records = [
        _row(1, 10, 11, 7, 8), _row(2, 7.5, 12, 7, 11.5),
        _row(3, 10, 13, 9, 12), _row(4, 12.5, 13, 8, 9),
    ]
    original = deepcopy(records)
    events   = detect_candlestick_patterns(records=records)
    assert records == original
    assert any(event["pattern_id"] == "bullish_engulfing" and event["direction"] == 1 for event in events)
    assert any(event["pattern_id"] == "bearish_engulfing" and event["direction"] == -1 for event in events)
    assert all(0 <= event["confidence"] <= 1 for event in events)
    assert all("label" not in event and "color" not in event for event in events)


def test_patterns_require_enough_records_for_multicandle_structures():
    events = detect_candlestick_patterns(records=[_row(1, 10, 11, 9, 10.5)])
    assert not any(event["pattern_id"] in {"morning_star", "evening_star", "three_white_soldiers", "three_black_crows"} for event in events)
