from liquidity_microstructure_helpers import valid_fetcher
from processing_signals.input.input_pipeline import INPUT_FAMILY_HANDLERS, run_input_pipeline
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS
from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS
from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS


def test_only_input_handler_is_registered():
    assert "liquidity_microstructure" in INPUT_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in PROCESSING_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in CLASSIFICATION_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in VERTICAL_FAMILY_HANDLERS


def test_input_pipeline_executes_prices_and_liquidity_separately():
    output = run_input_pipeline(enabled_families=("liquidity_microstructure",),
                                family_arguments={"liquidity_microstructure": {"fetcher": valid_fetcher,
                                                                               "reference_timestamp": 1_700_000_000}})
    assert tuple(output) == ("liquidity_microstructure",)
