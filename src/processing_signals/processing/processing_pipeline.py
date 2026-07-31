from __future__                           import annotations
from typing                               import Any, Mapping, Sequence
from .prices_ohlcv.prices_ohlcv_processor import run_prices_ohlcv_processing
from .long_short_liquidations.long_short_liquidations_processor import process_long_short_liquidations
from .on_chain_miners.on_chain_miners_processor import process_on_chain_miners
from .etf_exchange_flows import run_etf_exchange_flows_processing

def _run_long_short_liquidations_processing_adapter(input_contract: Mapping[str, Any], *,
                                                     existing_processing: Mapping[str, Any] | None,
                                                     now_timestamp: int | None,
                                                     family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    return process_long_short_liquidations(input_contract, **dict(family_arguments))

def _run_on_chain_miners_processing_adapter(input_contract: Mapping[str, Any], *,
                                             existing_processing: Mapping[str, Any] | None,
                                             now_timestamp: int | None,
                                             family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    del existing_processing, now_timestamp
    if family_arguments:
        raise ValueError("on_chain_miners Processing does not accept family arguments")
    return process_on_chain_miners(input_contract)

def _run_etf_exchange_flows_processing_adapter(input_contract: Mapping[str, Any], *,
                                                existing_processing: Mapping[str, Any] | None,
                                                now_timestamp: int | None,
                                                family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    del existing_processing
    arguments = dict(family_arguments)
    if "generated_at" not in arguments and now_timestamp is not None:
        arguments["generated_at"] = now_timestamp
    return run_etf_exchange_flows_processing(input_contract=input_contract, **arguments)

PROCESSING_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_processing,
                              "long_short_liquidations": _run_long_short_liquidations_processing_adapter,
                              "on_chain_miners": _run_on_chain_miners_processing_adapter,
                              "etf_exchange_flows": _run_etf_exchange_flows_processing_adapter}

def run_processing_pipeline(*, input_contracts: Mapping[str, Mapping[str, Any]], enabled_families: Sequence[str] = ("prices_ohlcv",),
                            existing_processing: Mapping[str, Mapping[str, Any]] | None = None,
                            now_timestamp: int | None = None,
                            family_arguments: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    existing = existing_processing or {}
    arguments = family_arguments or {}
    outputs  = {}
    for family in enabled_families:
        handler = PROCESSING_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No Processing handler registered for family: {family}")
        if family not in input_contracts:
            raise ValueError(f"Input contract missing for family: {family}")
        if family == "prices_ohlcv":
            outputs[family] = handler(input_contracts[family], existing_processing=existing.get(family),
                                      now_timestamp=now_timestamp, **dict(arguments.get(family, {})))
        else:
            outputs[family] = handler(input_contracts[family], existing_processing=existing.get(family),
                                      now_timestamp=now_timestamp, family_arguments=dict(arguments.get(family, {})))
    return outputs
