import json
from copy import deepcopy

import pytest

from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


@pytest.mark.parametrize("field,value", [("family", "wrong"), ("stage", "wrong")])
def test_invalid_root_contract_is_rejected(field, value):
    source = liquidity_input()
    source[field] = value
    with pytest.raises(ValueError):
        process_liquidity_microstructure(source)


def test_invalid_input_quality_returns_stable_invalid_output():
    source = liquidity_input()
    source["quality"]["status"] = "invalid"
    result = process_liquidity_microstructure(source, now_timestamp=123)
    assert result["quality"]["status"] == "invalid"
    assert result["quality"]["reason"] == "input_quality_invalid"


def test_strict_json_and_config_immutability():
    source, config = liquidity_input(), {"market_impact_quantity_base": 2.0}
    original = deepcopy(config)
    output = process_liquidity_microstructure(source, config=config)
    json.dumps(output, allow_nan=False)
    assert config == original
