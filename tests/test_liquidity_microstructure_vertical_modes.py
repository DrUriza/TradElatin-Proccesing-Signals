import pytest

from liquidity_microstructure_vertical_helpers import arguments
from processing_signals.main.liquidity_microstructure import run_liquidity_microstructure_vertical


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_modes(mode):
    bootstrap = run_liquidity_microstructure_vertical(**arguments())
    extra = {"mode": mode}
    if mode != "bootstrap":
        extra.update(existing_input=bootstrap["input"], existing_processing=bootstrap["processing"])
    if mode == "recovery":
        extra["recovery_requests"] = ["market_data_history"]
    result = run_liquidity_microstructure_vertical(**arguments(**extra))
    assert result["mode"] == mode and result["screen_contract"]["mode"] == mode
