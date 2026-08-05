from copy import deepcopy

import pytest

from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS, run_classification_pipeline


def test_registered_default_unchanged_and_arguments_routed():
    assert "liquidity_microstructure" in CLASSIFICATION_FAMILY_HANDLERS
    source = processing_contract()
    original = deepcopy(source)
    result = run_classification_pipeline(processing_contracts={"liquidity_microstructure": source},
                                         enabled_families=("liquidity_microstructure",),
                                         family_arguments={"liquidity_microstructure": {"now_timestamp": 1_700_000_001}})
    assert list(result) == ["liquidity_microstructure"]
    assert result["liquidity_microstructure"]["execution_timestamp"] == 1_700_000_001
    assert source == original


def test_unknown_and_missing_processing_fail():
    with pytest.raises(ValueError):
        run_classification_pipeline(processing_contracts={}, enabled_families=("unknown",))
    with pytest.raises(ValueError):
        run_classification_pipeline(processing_contracts={}, enabled_families=("liquidity_microstructure",))
