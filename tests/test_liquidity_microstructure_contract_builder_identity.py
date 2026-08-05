from liquidity_microstructure_contract_builder_helpers import bundle, runtime
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


def test_identity_defaults_and_inventories():
    result = build_liquidity_microstructure_screen_contract(bundle(), runtime_context=runtime())
    assert result["schema"] == {"id": "trad_elatin.liquidity_microstructure.screen.v1", "version": "1.0.0"}
    assert (result["screen"]["id"], result["screen"]["route"], result["stage"]) == ("liquidity_microstructure", "/liquidity", "screen_contract")
    assert (result["context"]["selected_market"], result["context"]["selected_timeframe"]) == ("perpetual", "1m")
    assert len(result["kpis"]["items"]) == 6 and len(result["charts"]) == 6 and len(result["drilldowns"]) == 6
