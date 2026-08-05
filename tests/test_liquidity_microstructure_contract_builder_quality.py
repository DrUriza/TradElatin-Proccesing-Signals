from liquidity_microstructure_contract_builder_helpers import bundle, runtime
# ruff: noqa: E702
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import LiquidityMicrostructureContractBuilder


def test_builder_facade_returns_stable_invalid_fallback():
    source = bundle(); source["classification"]["reference_timestamp"] += 1
    result = LiquidityMicrostructureContractBuilder().run(source, runtime_context=runtime())
    assert result["quality"]["status"] == "invalid" and result["quality"]["contract_complete"] is True
    assert len(result["kpis"]["items"]) == 6 and set(result["charts"]) and set(result["tables"])
    assert all(row["status"] == "invalid" for row in result["kpis"]["items"])
