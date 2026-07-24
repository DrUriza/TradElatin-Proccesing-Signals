from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv.prices_ohlcv_processor import run_prices_ohlcv_processing


PROCESSING_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_processing}


def run_processing_pipeline(*, input_contracts: Mapping[str, Mapping[str, Any]], enabled_families: Sequence[str] = ("prices_ohlcv",),
                            existing_processing: Mapping[str, Mapping[str, Any]] | None = None,
                            now_timestamp: int | None = None) -> dict[str, Any]:
    existing = existing_processing or {}
    outputs  = {}
    for family in enabled_families:
        handler = PROCESSING_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No Processing handler registered for family: {family}")
        if family not in input_contracts:
            raise ValueError(f"Input contract missing for family: {family}")
        outputs[family] = handler(input_contracts[family], existing_processing=existing.get(family), now_timestamp=now_timestamp)
    return outputs
