from liquidity_microstructure_vertical_helpers import arguments
from processing_signals.main.liquidity_microstructure import LiquidityMicrostructureVertical, run_liquidity_microstructure_vertical


def test_bootstrap_public_api_and_stage_order():
    result = run_liquidity_microstructure_vertical(**arguments())
    assert [result[key]["stage"] for key in ("input", "processing", "classification", "screen_contract")] == ["input", "processing", "classification", "screen_contract"]
    assert result["family"] == "liquidity_microstructure" and len(result["screen_contract"]["kpis"]["items"]) == 6
    assert LiquidityMicrostructureVertical(**arguments()).run()["screen_contract"] == result["screen_contract"]
