from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS
from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS, run_processing_pipeline


def test_registered_only_in_processing_pipeline():
    assert "liquidity_microstructure" in PROCESSING_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in CLASSIFICATION_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in VERTICAL_FAMILY_HANDLERS
    result = run_processing_pipeline(input_contracts={"liquidity_microstructure": liquidity_input()},
                                     enabled_families=("liquidity_microstructure",), now_timestamp=123)
    assert tuple(result) == ("liquidity_microstructure",)
