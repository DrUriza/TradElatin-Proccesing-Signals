from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path

from processing_signals.main.long_short_liquidations import run_long_short_liquidations_vertical

REFERENCE = 1_740_000_000
CONTEXT = {"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT",
           "market": "futures", "price_precision": 2}
SIDE_IDS = ["pressure_score", "selected_realized_side", "selected_realized_imbalance", "realized_side_24h",
    "realized_imbalance_24h", "estimated_side", "estimated_imbalance", "exchange_concentration",
    "aggregate_map_concentration", "event_activity_15m", "selected_window_largest_event",
    "nearest_estimated_long_cluster", "nearest_estimated_short_cluster", "provider_confirmations", "max_pain",
    "screen_quality_summary"]

_SPEC = importlib.util.spec_from_file_location("approved_long_short_input_fixtures",
    Path(__file__).with_name("test_long_short_liquidations_input_vertical.py"))
_FIXTURES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_FIXTURES)


class SyntheticLiquidationsFetcher:
    def __init__(self, timestamp: int = REFERENCE, updated_value: float = 1.) -> None:
        self.timestamp, self.updated_value, self.calls = timestamp, updated_value, []

    def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        result = deepcopy(_FIXTURES._nominal_fetcher(**kwargs))
        endpoint = kwargs["endpoint_id"]
        if endpoint in {"aggregated_liquidation_history", "pair_liquidation_history"}:
            long_key = "aggregated_long_liquidation_usd" if endpoint.startswith("aggregated") else "long_liquidation_usd"
            short_key = "aggregated_short_liquidation_usd" if endpoint.startswith("aggregated") else "short_liquidation_usd"
            result["data"] = [{"time": REFERENCE * 1000, long_key: self.updated_value, short_key: 2},
                              {"time": self.timestamp * 1000, long_key: 3, short_key: 4}]
        elif endpoint == "liquidation_order_events":
            result["data"][0]["time"] = self.timestamp * 1000
        return result


def vertical_arguments(timestamp: int = REFERENCE, *, mode: str = "bootstrap", fetcher=None, previous_state=None,
                       recovery_requests=None):
    fetcher = fetcher or SyntheticLiquidationsFetcher(timestamp)
    input_arguments = {"requested_mode": mode, "exchanges": ("Binance",),
        "exchange_pairs": {"Binance": "BTCUSDT"}, "cryptoquant_exchanges": ("binance",)}
    if recovery_requests is not None:
        input_arguments["recovery_requests"] = recovery_requests
    arguments = {"fetcher": fetcher, "input_arguments": input_arguments,
        "processing_arguments": {"reference_price_context": {"value": 50_000, "timestamp": timestamp,
            "source_family": "prices_ohlcv", "source_market": "futures", "source_timeframe": "1m",
            "price_field": "close", "is_closed_bar": True}},
        "contract_arguments": {"context": CONTEXT},
        "now_timestamp": timestamp,
        "runtime_metadata": {"data_mode": "synthetic", "is_demo": True, "cache_status": "disabled"}}
    if previous_state is not None:
        arguments["previous_state"] = previous_state
    return arguments


def run_vertical(timestamp: int = REFERENCE, **kwargs):
    return run_long_short_liquidations_vertical(**vertical_arguments(timestamp, **kwargs))
