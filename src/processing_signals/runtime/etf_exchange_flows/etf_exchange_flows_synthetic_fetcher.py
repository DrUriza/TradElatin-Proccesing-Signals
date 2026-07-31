"""Offline provider-shaped responses for the ETF exchange-flow demo."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP = 1_740_000_000

COINGLASS_ENDPOINTS = {
    "bitcoin_etf_flows",
    "bitcoin_etf_list",
    "bitcoin_etf_net_assets_history",
    "bitcoin_etf_premium_discount_history",
    "exchange_balance_list",
    "exchange_balance_chart",
}
CRYPTOQUANT_FIELDS = {
    "exchange_inflow": "inflow_total",
    "exchange_outflow": "outflow_total",
    "exchange_netflow": "netflow_total",
    "exchange_reserve": "reserve",
}
GLASSNODE_ENDPOINTS = {
    "exchange_balance",
    "us_spot_etf_flows_net",
    "exchange_netflow",
    "exchange_inflow",
    "exchange_outflow",
}


def build_etf_exchange_flows_synthetic_body(*, provider: str, endpoint_id: str,
                                             params: dict[str, Any],
                                             timestamp: int = ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP) -> Any:
    """Return an approved provider-shaped payload without network access."""
    if provider == "coinglass" and endpoint_id in COINGLASS_ENDPOINTS:
        rows = {
            "bitcoin_etf_flows": [{"timestamp": timestamp * 1000, "flow_usd": 10.0, "price_usd": 50_000.0,
                "etf_flows": [{"etf_ticker": "GBTC", "flow_usd": -2.0},
                              {"etf_ticker": "IBIT", "flow_usd": 12.0}]}],
            "bitcoin_etf_list": [
                {"ticker": "GBTC", "fund_name": "Grayscale Bitcoin Trust", "shares_outstanding": "10",
                 "aum_usd": "400.0", "management_fee_percent": "1.5", "asset_details": {}},
                {"ticker": "IBIT", "fund_name": "iShares Bitcoin Trust", "shares_outstanding": "20",
                 "aum_usd": "600.0", "management_fee_percent": "0.25", "asset_details": {}},
            ],
            "bitcoin_etf_net_assets_history": [{"timestamp": timestamp * 1000, "net_assets_usd": 1_100.0,
                "change_usd": 10.0, "price_usd": 50_000.0}],
            "bitcoin_etf_premium_discount_history": [{"timestamp": timestamp * 1000, "list": [
                {"ticker": "GBTC", "nav_usd": 10.0, "market_price_usd": 9.9,
                 "premium_discount_details": -1.0}]}],
            "exchange_balance_list": [
                {"exchange_name": "Coinbase", "total_balance": 100.0,
                 "balance_change_1d": None, "balance_change_percent_1d": 0.0},
                {"exchange_name": "Binance", "total_balance": 200.0,
                 "balance_change_1d": None, "balance_change_percent_1d": 0.0},
            ],
            "exchange_balance_chart": [{"time_list": [timestamp * 1000], "price_list": [50_000.0],
                "data_map": {"coinbase": [100.0], "binance": [200.0]}}],
        }[endpoint_id]
        return {"code": "0", "msg": "success", "data": rows}
    if provider == "cryptoquant" and endpoint_id in CRYPTOQUANT_FIELDS:
        field = CRYPTOQUANT_FIELDS[endpoint_id]
        values = {"exchange_inflow": 2.0, "exchange_outflow": 1.0,
                  "exchange_netflow": 1.0, "exchange_reserve": 1_000.0}
        row = {"date": "2025-02-19T21:20:00Z", field: values[endpoint_id]}
        if endpoint_id in {"exchange_inflow", "exchange_outflow"}:
            prefix = endpoint_id.removeprefix("exchange_")
            row[f"{prefix}_top10"] = values[endpoint_id]
            row[f"{prefix}_mean"] = values[endpoint_id]
        return {"status": {"code": 200, "message": "success"},
                "result": {"window": params["window"], "data": [row]}}
    if provider == "glassnode" and endpoint_id in GLASSNODE_ENDPOINTS:
        value = 990.0 if endpoint_id == "exchange_balance" else 1.5
        return [{"t": timestamp, "v": value}]
    raise ValueError(f"unknown_synthetic_endpoint:{provider}:{endpoint_id}")


class EtfExchangeFlowsSyntheticFetcher:
    """Callable matching the frozen Input ETF fetcher protocol."""

    def __init__(self, timestamp: int = ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP) -> None:
        if type(timestamp) is not int or timestamp <= 0:
            raise ValueError("timestamp must be a positive integer")
        self.timestamp = timestamp
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> Any:
        provider = kwargs.get("provider")
        endpoint_id = kwargs.get("endpoint_id")
        params = kwargs.get("params")
        if not isinstance(provider, str) or not isinstance(endpoint_id, str) or not isinstance(params, dict):
            raise ValueError("invalid_synthetic_fetch_request")
        self.calls.append(deepcopy(kwargs))
        return build_etf_exchange_flows_synthetic_body(provider=provider, endpoint_id=endpoint_id,
            params=deepcopy(params), timestamp=self.timestamp)
