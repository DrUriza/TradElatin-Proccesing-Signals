"""Synthetic runtime support for the ETF exchange-flow demo contract."""

from .etf_exchange_flows_synthetic_fetcher import (
    ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP,
    EtfExchangeFlowsSyntheticFetcher,
    build_etf_exchange_flows_synthetic_body,
)

__all__ = [
    "ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP",
    "EtfExchangeFlowsSyntheticFetcher",
    "build_etf_exchange_flows_synthetic_body",
]
