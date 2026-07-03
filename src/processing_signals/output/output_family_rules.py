from __future__ import annotations
from typing     import Any


INPUT_OFFICIAL_FAMILIES = {
    "prices_ohlcv",
    "volume_orderflow",
    "liquidity_microstructure",
    "institutional_flows",
    "liquidations",
    "derivatives_open_interest",
    "sentiment_positioning",
    "on_chain_miners",
    "options_volatility",
}


def resolve_output_family(block: dict[str, Any]) -> dict[str, str]:
    detected = block.get("detected", {})
    normalized = block.get("normalized", {})
    metadata = detected.get("metadata", {}) if isinstance(detected.get("metadata"), dict) else {}
    data_type = str(detected.get("data_type") or "").lower()
    canonical_type = str(detected.get("canonical_type") or "").lower()
    kind = str(normalized.get("kind") or "").lower()
    shape_source = " ".join([data_type, canonical_type, kind])
    input_family = str(
        detected.get("suggested_family_key")
        or metadata.get("family_key")
        or metadata.get("family")
        or ""
    ).lower()

    if input_family in INPUT_OFFICIAL_FAMILIES:
        output_shape = _input_family_shape(input_family, data_type, canonical_type, kind, metadata)
        return _family(input_family, output_shape, f"{output_shape}.json")

    if any(
        token in data_type
        for token in ["miner", "mining", "hash_rate", "hashrate", "miner_ratio","miner_inflow",
                      "miner_outflow", "miner_netflow", "difficulty", "network_health"]):
        output_shape = _network_or_onchain_shape(shape_source)
        return _family("mining_network_health", output_shape, f"{output_shape}.json")

    if any(
        token in data_type
        for token in [
            "onchain",
            "on_chain",
            "glassnode",
            "holder",
            "holders",
            "cohort",
            "cohorts",
            "accumulation",
            "distribution",
            "exchange_balance",
            "mvrv",
            "nvt",
            "sopr",
            "realized_cap",
            "supply_in_profit",
            "supply_in_loss",
            "long_term_holder",
            "short_term_holder",
        ]
    ):
        output_shape = _network_or_onchain_shape(shape_source)
        return _family("onchain_holder_behavior", output_shape, f"{output_shape}.json")

    if data_type == "candlestick":
        return _family("prices_ohlcv", "candlestick", "candlestick.json")

    if data_type == "orderbook_conventional":
        return _family("liquidity_microstructure", "conventional_orderbook", "conventional_orderbook.json")

    if data_type == "orderbook_large_trades":
        return _family("liquidity_microstructure", "large_trades_orderbook", "large_trades_orderbook.json")

    if data_type == "orderbook_whale_orders":
        return _family(
            "liquidity_microstructure",
            "whale_orders_orderbook",
            "whale_orders_orderbook.json",
        )

    if data_type == "manifest":
        return _family("metadata", "manifest", "manifest.json", is_metadata=True)

    if "cvd" in data_type or "volume" in data_type:
        output_shape = _volume_orderflow_shape(data_type, shape_source)
        return _family("volume_orderflow", output_shape, f"{output_shape}.json")

    if any(token in data_type for token in ["etf", "exchange_flow", "netflow", "inflow", "outflow"]):
        output_shape = _institutional_shape(shape_source)
        return _family("institutional_flows", output_shape, f"{output_shape}.json")

    if "liquidation" in data_type:
        output_shape = _institutional_shape(shape_source)
        return _family("liquidations", output_shape, f"{output_shape}.json")

    if "long_short" in data_type:
        output_shape = _sentiment_shape(shape_source)
        return _family("sentiment_positioning", output_shape, f"{output_shape}.json")

    if "open_interest" in data_type or data_type == "oi":
        output_shape = _open_interest_shape(shape_source)
        return _family("derivatives_open_interest", output_shape, f"{output_shape}.json")

    if "whale" in data_type:
        return _family(
            "liquidity_microstructure",
            "whale_orders_orderbook",
            "whale_orders_orderbook.json",
        )

    return _family("unknown", "unknown", "unknown.json")


def _family(
    family_key: str,
    output_shape: str,
    output_filename: str,
    is_metadata: bool = False,
) -> dict[str, Any]:
    return {
        "family_key": family_key,
        "output_shape": output_shape,
        "output_filename": output_filename,
        "output_file_key": f"{family_key}/{output_shape}",
        "is_metadata": is_metadata,
    }


def _volume_orderflow_shape(data_type: str, shape_source: str) -> str:
    if "cvd" in data_type and ("candlestick_derived" in shape_source or "derived" in shape_source):
        return "cvd_candlestick_derived"
    if "cvd" in data_type:
        return "cvd_time_series"
    if "bar" in shape_source:
        return "volume_bar"
    return "volume_features"


def _input_family_shape(
    family_key: str,
    data_type: str,
    canonical_type: str,
    kind: str,
    metadata: dict[str, Any],
) -> str:
    input_data_type = str(metadata.get("input_data_type") or "").lower()
    shape_source = " ".join([data_type, canonical_type, kind, input_data_type])

    if data_type == "candlestick" or input_data_type == "candlestick":
        return "candlestick"
    if input_data_type in {"bars", "event_list", "heatmap", "snapshot"}:
        if family_key == "liquidity_microstructure" and input_data_type == "snapshot":
            return "event_list"
        return input_data_type

    if family_key == "prices_ohlcv":
        return "time_series"
    if family_key == "volume_orderflow":
        return _volume_orderflow_shape(data_type, shape_source)
    if family_key == "liquidity_microstructure":
        if data_type == "orderbook_conventional":
            return "conventional_orderbook"
        if data_type == "orderbook_large_trades":
            return "large_trades_orderbook"
        if data_type == "orderbook_whale_orders":
            return "whale_orders_orderbook"
        if "wall" in data_type or "trade" in data_type or "whale" in data_type:
            return "event_list"
        return "time_series"
    if family_key in {"institutional_flows", "liquidations"}:
        return _institutional_shape(shape_source)
    if family_key == "derivatives_open_interest":
        return _open_interest_shape(shape_source)
    if family_key == "sentiment_positioning":
        return _sentiment_shape(shape_source)
    if family_key == "on_chain_miners":
        return _network_or_onchain_shape(shape_source)
    if family_key == "options_volatility":
        if "gamma" in data_type:
            return "heatmap"
        if "max_pain" in data_type:
            return "snapshot"
        return "time_series"
    return input_data_type or kind or canonical_type or "time_series"


def _institutional_shape(shape_source: str) -> str:
    if "candlestick_derived" in shape_source or "derived" in shape_source:
        return "candlestick_derived"
    if "event" in shape_source:
        return "event_list"
    if "bar" in shape_source:
        return "bar"
    return "time_series"


def _open_interest_shape(shape_source: str) -> str:
    if "regime" in shape_source:
        return "regimes"
    if "candlestick_derived" in shape_source or "derived" in shape_source:
        return "candlestick_derived"
    return "time_series"


def _sentiment_shape(shape_source: str) -> str:
    if "candlestick_derived" in shape_source or "derived" in shape_source:
        return "candlestick_derived"
    if "bar" in shape_source:
        return "bar"
    return "time_series"


def _network_or_onchain_shape(shape_source: str) -> str:
    if "regime" in shape_source:
        return "regimes"
    if "event" in shape_source:
        return "event_list"
    if "bar" in shape_source:
        return "bars"
    return "time_series"
