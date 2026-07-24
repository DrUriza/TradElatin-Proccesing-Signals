from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv.prices_ohlcv_data_raw_preprocessing import run_prices_ohlcv_input


INPUT_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_input}


def run_input_pipeline(*, enabled_families: Sequence[str] = ("prices_ohlcv",),
                       family_arguments: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    arguments = family_arguments or {}
    outputs   = {}
    for family in enabled_families:
        handler = INPUT_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No Input handler registered for family: {family}")
        outputs[family] = handler(**dict(arguments.get(family, {})))
    return outputs
