from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def test_whale_is_statistical_only_and_market_history_uses_past_observation():
    result = process_liquidity_microstructure(liquidity_input())
    whale = result["whale_activity"]["timeframes"]["1h"]
    assert whale["statistics"]["reason"] == "insufficient_data"
    assert not {"bullish", "bearish", "accumulation", "distribution"}.intersection(str(result))
    history = result["market_history"]
    assert history["changes"]["7d"]["source_timestamp"] == 1_700_000_000 - 7 * 86400
    assert history["changes"]["1d"]["source_timestamp"] == 1_700_000_000 - 7 * 86400
