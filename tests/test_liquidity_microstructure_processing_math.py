import pytest

from processing_signals.processing.math.microstructure.order_book import depth_metrics, process_order_book_levels
from processing_signals.processing.math.microstructure.series_metrics import rolling_z_score, safe_percent_change


def test_signed_imbalance_is_not_bid_share():
    result = depth_metrics(195.82, 244.02)
    assert result["bid_share_percent"] == pytest.approx(44.52, abs=.01)
    assert result["ask_share_percent"] == pytest.approx(55.48, abs=.01)
    assert result["imbalance_percent"] == pytest.approx(-10.96, abs=.01)
    assert result["bid_share_percent"] != result["imbalance_percent"]


def test_orderbook_consolidation_bands_and_statistics():
    result = process_order_book_levels([{"price": 99, "quantity": .5}, {"price": 99, "quantity": .5}, {"price": 98, "quantity": 0}],
                                       [{"price": 101, "quantity": 1}], impact_quantity=1)
    assert result["mid_price"] == 100
    assert result["spread_quote"] == 2
    assert result["metadata"]["bids"]["duplicate_prices_consolidated"] == 1
    assert result["metadata"]["bids"]["zero_quantity_levels_excluded"] == 1
    assert result["market_impact"]["buy"]["fully_filled"] is True
    assert safe_percent_change(1, 0) is None
    assert rolling_z_score([1] * 20, 20) is None
