from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv.prices_ohlcv_classifier import run_prices_ohlcv_classification


CLASSIFICATION_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_classification}


def run_classification_pipeline(*, processing_contracts: Mapping[str, Mapping[str, Any]],
                                enabled_families: Sequence[str] = ("prices_ohlcv",)) -> dict[str, Any]:
    outputs = {}
    for family in enabled_families:
        handler = CLASSIFICATION_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No Classification handler registered for family: {family}")
        if family not in processing_contracts:
            raise ValueError(f"Processing contract missing for family: {family}")
        outputs[family] = handler(processing_contracts[family])
    return outputs
