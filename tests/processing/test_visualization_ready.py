from __future__ import annotations

from pathlib import Path

import pandas as pd

from processing_signals.input.apis.coinglass.endpoint_registry_coinglass import SYNTHETIC_TIMEFRAMES as COINGLASS_SYNTHETIC
from processing_signals.input.apis.cryptoquant.endpoint_registry_cryptoquant import SYNTHETIC_TIMEFRAMES as CRYPTOQUANT_SYNTHETIC
from processing_signals.input.apis.external_indices.endpoint_registry import SYNTHETIC_TIMEFRAMES as EXTERNAL_SYNTHETIC
from processing_signals.input.apis.glassnode.endpoint_registry_glassnode import SYNTHETIC_TIMEFRAMES as GLASSNODE_SYNTHETIC
from processing_signals.output.visualization_ready_builder import VisualizationReadyBuilder
from processing_signals.output.visualization_ready_validator import VisualizationReadyValidator
from processing_signals.processing.detection.data_type_detector import DataTypeDetector
from processing_signals.processing.normalization.normalizer import Normalizer


def test_normalizer_parses_millisecond_timestamps_without_1970_artifact():
    payload = {
        "records": [
            {"time": 1782238500000, "value": 1.0},
            {"time": 1782239400000, "value": 1.5},
        ]
    }
    detected = {"data_type": "basis", "symbol": "BTCUSDT", "timeframe": "15m"}

    normalized = Normalizer().normalize(payload, detected)
    df = normalized["dataframe"]

    assert "timestamp" in df.columns
    assert str(df["timestamp"].iloc[0].year) == "2026"


def test_data_type_detector_uses_subtype_from_time_series_metadata():
    payload = {
        "metadata": {
            "family": "derivatives_open_interest",
            "subtype": "basis",
            "data_type": "time_series",
            "symbol": "BTCUSDT",
            "timeframe": "15m",
        },
        "records": [{"time": 1782238500000, "value": 1.0}],
    }

    detected = DataTypeDetector().detect(payload, source_name="derivatives_open_interest/coinglass_basis_15m.json")

    assert detected["data_type"] == "basis"
    assert detected["canonical_type"] == "time_series"


def test_synthetic_timeframes_match_official_contract():
    expected = ["1m", "5m", "15m", "4h"]

    assert COINGLASS_SYNTHETIC == expected
    assert CRYPTOQUANT_SYNTHETIC == expected
    assert GLASSNODE_SYNTHETIC == expected
    assert EXTERNAL_SYNTHETIC == expected


def test_visualization_ready_outputs_flat_contract(tmp_path: Path):
    df = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(["2026-06-01T00:00:00Z", "2026-06-01T00:15:00Z"], utc=True),
            "value": [10.0, 11.0],
        }
    )
    block = {
        "source_name": "derivatives_open_interest/coinglass_basis_15m.json",
        "family_key": "derivatives_open_interest",
        "is_metadata": False,
        "detected": {
            "data_type": "basis",
            "timeframe": "15m",
            "symbol": "BTCUSDT",
        },
        "normalized": {
            "dataframe": df,
            "summary": {"rows": 2},
        },
    }

    builder = VisualizationReadyBuilder(tmp_path / "visualization_ready")
    index = builder.write([block])

    assert index["count"] == 1
    item = index["files"][0]
    assert item["family"] == "derivatives_open_interest"
    assert item["data_type"] == "basis"
    assert item["timeframe"] == "15m"
    assert item["records"] == 2
    assert item["timestamp_field"] == "timestamp"


def test_visualization_validator_flags_unknown_recognizable_data_type():
    block = {
        "source_name": "derivatives_open_interest/coinglass_open_interest_15m.json",
        "family_key": "derivatives_open_interest",
        "detected": {"data_type": "unknown", "timeframe": "15m"},
        "normalized": {
            "dataframe": pd.DataFrame(
                {
                    "timestamp": pd.to_datetime(["2026-06-01T00:00:00Z"], utc=True),
                    "open_interest": [123.0],
                }
            )
        },
    }

    validator = VisualizationReadyValidator()
    report = validator.validate([block], {"files": []})

    assert report["status"] == "failed"
    assert any("data_type is unknown" in error for error in report["errors"])
