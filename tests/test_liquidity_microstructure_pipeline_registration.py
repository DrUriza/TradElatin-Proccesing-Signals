from liquidity_microstructure_helpers import valid_fetcher
from processing_signals.input.input_pipeline import INPUT_FAMILY_HANDLERS, run_input_pipeline
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS
from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS
from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS


def test_processing_registration_supersedes_the_previous_input_only_expectation():
    assert "liquidity_microstructure" in INPUT_FAMILY_HANDLERS
    assert "liquidity_microstructure" in PROCESSING_FAMILY_HANDLERS
    assert "liquidity_microstructure" in CLASSIFICATION_FAMILY_HANDLERS
    assert "liquidity_microstructure" in VERTICAL_FAMILY_HANDLERS


def test_input_pipeline_executes_prices_and_liquidity_separately():
    def prices_fetcher(**request):
        return {"code": 0, "data": [{"time": 1_700_000_000_000, "open": 100, "high": 102,
                                       "low": 99, "close": 101, "volume": 10}]}
    output = run_input_pipeline(enabled_families=("prices_ohlcv", "liquidity_microstructure"),
                                family_arguments={"prices_ohlcv": {"fetcher": prices_fetcher},
                                                  "liquidity_microstructure": {"fetcher": valid_fetcher,
                                                                               "reference_timestamp": 1_700_000_000}})
    assert tuple(output) == ("prices_ohlcv", "liquidity_microstructure")
