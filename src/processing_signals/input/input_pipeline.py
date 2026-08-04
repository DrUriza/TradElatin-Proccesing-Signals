from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv.prices_ohlcv_data_raw_preprocessing import run_prices_ohlcv_input
from .long_short_liquidations.long_short_liquidations_data_raw_preprocessing import run_long_short_liquidations_input
from .on_chain_miners.on_chain_miners_data_raw_preprocessing import run_on_chain_miners_input
from .etf_exchange_flows.etf_exchange_flows_data_raw_preprocessing import run_etf_exchange_flows_input
from .liquidity_microstructure.liquidity_microstructure_data_raw_preprocessing import run_liquidity_microstructure_input


INPUT_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_input,
                         "long_short_liquidations": run_long_short_liquidations_input,
                         "on_chain_miners": run_on_chain_miners_input,
                         "etf_exchange_flows": run_etf_exchange_flows_input,
                         "liquidity_microstructure": run_liquidity_microstructure_input}


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
