from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv import run_prices_vertical


VERTICAL_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_vertical}


def run_main_pipeline(*, enabled_families: Sequence[str] = ("prices_ohlcv",),
                      family_arguments: Mapping[str, Mapping[str, Any]] | None = None,
                      previous_state: Mapping[str, Mapping[str, Any]] | None = None,
                      screens_only: bool = False) -> dict[str, Any]:
    arguments = family_arguments or {}
    previous  = previous_state or {}
    outputs   = {}
    for family in enabled_families:
        handler = VERTICAL_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No vertical handler registered for family: {family}")
        family_output  = handler(previous_state=previous.get(family), **dict(arguments.get(family, {})))
        outputs[family] = family_output["screen"] if screens_only else family_output
    return outputs
