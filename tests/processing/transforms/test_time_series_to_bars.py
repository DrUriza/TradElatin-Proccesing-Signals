from __future__ import annotations

import pandas as pd

from processing_signals.processing.transforms.time_series_to_bars import time_series_to_bars


def test_time_series_to_bars_uses_cvd_not_time() -> None:
    records, reference, warning = time_series_to_bars(
        pd.DataFrame({"time": [1782172800000], "cvd": [12.5]}),
        semantic_subtype="cvd",
    )

    assert reference == "cvd"
    assert warning is None
    assert records[0]["open"] == 12.5


def test_time_series_to_bars_uses_open_interest_not_timestamp() -> None:
    records, reference, warning = time_series_to_bars(
        pd.DataFrame({"timestamp": [1782172800], "open_interest": [1000.0]}),
        semantic_subtype="open_interest",
    )

    assert reference == "open_interest"
    assert warning is None
    assert records[0]["close"] == 1000.0


def test_time_series_to_bars_uses_funding_rate_not_datetime() -> None:
    records, reference, warning = time_series_to_bars(
        pd.DataFrame({"datetime": [1782172800000], "funding_rate": [0.0001]}),
        semantic_subtype="funding_rate",
    )

    assert reference == "funding_rate"
    assert warning is None
    assert records[0]["high"] == 0.0001


def test_time_series_to_bars_returns_warning_without_valid_metric() -> None:
    records, reference, warning = time_series_to_bars(
        pd.DataFrame({"time": [1782172800000], "blockheight": [850000]}),
        semantic_subtype="unknown",
    )

    assert records == []
    assert reference is None
    assert warning == "no_valid_reference_column"


def test_time_series_to_bars_uses_long_short_ratio_not_time() -> None:
    records, reference, warning = time_series_to_bars(
        pd.DataFrame({"time": [1782172800000], "long_short_ratio": [1.25]}),
        semantic_subtype="long_short_ratio",
    )

    assert reference == "long_short_ratio"
    assert warning is None
    assert records[0]["low"] == 1.25
