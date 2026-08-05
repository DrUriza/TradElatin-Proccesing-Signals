import inspect

from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS, run_main_pipeline


def test_main_registration_and_default():
    assert "prices_ohlcv" in VERTICAL_FAMILY_HANDLERS and "liquidity_microstructure" in VERTICAL_FAMILY_HANDLERS
    assert inspect.signature(run_main_pipeline).parameters["enabled_families"].default == ("prices_ohlcv", "liquidity_microstructure")
