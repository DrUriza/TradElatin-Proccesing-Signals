from __future__ import annotations

from typing import Any


UNKNOWN_FAMILY = "unknown"

OFFICIAL_FAMILIES = {
    "prices_ohlcv",
    "liquidity_microstructure",
    "cvd_volume_orderflow",
    "institutional_flows",
    "liquidations",
    "open_interest_and_funding",
    "sentiment_positioning",
    "onchain_miners",
    "options_volatility",
}

FAMILY_ALIASES = {
    "volume_orderflow": "cvd_volume_orderflow",
    "derivatives_open_interest": "open_interest_and_funding",
    "on_chain_miners": "onchain_miners",
}


def official_family_from(payload: dict[str, Any], metadata: dict[str, Any]) -> str:
    for value in [
        payload.get("family"),
        metadata.get("official_family"),
        metadata.get("family"),
        metadata.get("family_key"),
    ]:
        if value is not None and str(value).strip():
            return normalize_family(str(value))
    return UNKNOWN_FAMILY


def normalize_family(family: str) -> str:
    normalized = family.strip().lower()
    normalized = FAMILY_ALIASES.get(normalized, normalized)
    if normalized in OFFICIAL_FAMILIES:
        return normalized
    return UNKNOWN_FAMILY
