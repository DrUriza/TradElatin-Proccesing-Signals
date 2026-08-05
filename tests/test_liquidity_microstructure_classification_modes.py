import json
from copy import deepcopy

import pytest

from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_modes_determinism_json_and_immutability(mode):
    source = processing_contract(mode=mode)
    original = deepcopy(source)
    one = classify_liquidity_microstructure(source, now_timestamp=1_700_000_001)
    two = classify_liquidity_microstructure(source, now_timestamp=1_700_000_001)
    assert one == two and one["mode"] == mode and source == original
    json.dumps(one, ensure_ascii=False, allow_nan=False)
