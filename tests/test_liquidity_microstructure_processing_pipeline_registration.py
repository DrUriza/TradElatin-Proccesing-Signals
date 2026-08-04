from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS
from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS, run_processing_pipeline
from processing_signals.input.prices_ohlcv.prices_ohlcv_data_raw_preprocessing import run_prices_ohlcv_input
import inspect
import pytest


def test_registered_only_in_processing_pipeline():
    assert "liquidity_microstructure" in PROCESSING_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in CLASSIFICATION_FAMILY_HANDLERS
    assert "liquidity_microstructure" not in VERTICAL_FAMILY_HANDLERS
    result = run_processing_pipeline(input_contracts={"liquidity_microstructure": liquidity_input()},
                                     enabled_families=("liquidity_microstructure",), now_timestamp=123)
    assert tuple(result) == ("liquidity_microstructure",)
    assert inspect.signature(run_processing_pipeline).parameters["enabled_families"].default == ("prices_ohlcv",)
    with pytest.raises(ValueError, match="No Processing handler registered"):
        run_processing_pipeline(input_contracts={"unknown": {}}, enabled_families=("unknown",))


def test_prices_and_liquidity_execute_separately_in_requested_order():
    def prices_fetcher(**request):
        return {"code": 0, "data": [{"time": 1_700_000_000_000, "open": 100, "high": 102,
                                       "low": 99, "close": 101, "volume": 10}]}
    prices = run_prices_ohlcv_input(fetcher=prices_fetcher)
    result = run_processing_pipeline(input_contracts={"prices_ohlcv": prices, "liquidity_microstructure": liquidity_input()},
                                     enabled_families=("prices_ohlcv", "liquidity_microstructure"), now_timestamp=1_700_000_001)
    assert tuple(result) == ("prices_ohlcv", "liquidity_microstructure")
