"""Adversarial boundaries for ETF exchange-flow Classification."""
from copy import deepcopy
import hashlib
import math
from pathlib import Path

import pytest

from etf_exchange_flows_classification_helpers import NOW, cloned_processing
from processing_signals.classification.etf_exchange_flows import classify_etf_exchange_flows


@pytest.mark.parametrize("parameters", [
    {"pressure_neutral_threshold": True}, {"pressure_neutral_threshold": math.nan},
    {"pressure_strong_threshold": math.inf}, {"pressure_neutral_threshold": 0.5, "pressure_strong_threshold": 0.4},
    {"gbtc_discount_threshold_percent": 1}, {"aum_aligned_max_percent": 6, "aum_watch_max_percent": 5},
    {"netflow_deadband_btc": -1}, {"unknown": 1},
])
def test_invalid_parameter_overrides_are_rejected(parameters):
    with pytest.raises(ValueError, match="invalid_classification_input"):
        classify_etf_exchange_flows(processing_contract=cloned_processing(), generated_at=NOW, parameters=parameters)


@pytest.mark.parametrize(("path", "value"), [
    (("features", "pressure", "flow_24h", "value"), True),
    (("features", "pressure", "flow_24h", "value"), math.nan),
    (("features", "etf", "period_flow_usd", "1d", "value"), math.inf),
])
def test_bool_nan_infinity_are_rejected(path, value):
    processing = cloned_processing()
    target = processing
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    if isinstance(value, float) and not math.isfinite(value):
        with pytest.raises(ValueError, match="invalid_classification_input"):
            classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
    else:
        result = classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)
        assert result["classifications"]["exchange_pressure_regime"]["status"] == "invalid"


@pytest.mark.parametrize(("field", "value"), [("family", "other"), ("stage", "input"), ("version", "9")])
def test_incompatible_roots_are_rejected(field, value):
    processing = cloned_processing()
    processing[field] = value
    with pytest.raises(ValueError, match=f"invalid_classification_input:{field}"):
        classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW)


def test_no_visual_contract_pipeline_or_frozen_hash_changes():
    root = Path(__file__).parents[1]
    package = root / "src/processing_signals/classification/etf_exchange_flows"
    source = "\n".join(path.read_text(encoding="utf-8") for path in package.glob("*.py"))
    assert all(token not in source for token in ("display_value", "color", "widget", "requests", "httpx", "getenv", "environ"))
    expected = {
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_extract.py": "2E98421B5F7502877552E3DBCA6EEF3774CCD9C4476325AAE61D2B47B9A0C8CC",
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_preprocessing.py": "8353C2AE7227EDBB23D3F70B00363975FC6B44F6639AAFE47F5743E3DE1953BE",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_feature_builder.py": "832FD3A63D7A0C0A3E56474948587B468225ECE06E250869E0C2B802334BCD72",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_processor.py": "D8590C91815936074F837041DC8D354646C854EA9EDB754863DCAEAF850B014E",
    }
    actual = {path: hashlib.sha256((root / path).read_bytes()).hexdigest().upper() for path in expected}
    assert actual == expected


def test_reordered_input_is_deterministic():
    processing = cloned_processing()
    reordered = {key: deepcopy(processing[key]) for key in reversed(processing)}
    assert classify_etf_exchange_flows(processing_contract=processing, generated_at=NOW) == \
        classify_etf_exchange_flows(processing_contract=reordered, generated_at=NOW)
