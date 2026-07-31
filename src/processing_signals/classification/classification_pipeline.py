from __future__ import annotations

from typing import Any, Mapping, Sequence

from .prices_ohlcv.prices_ohlcv_classifier import run_prices_ohlcv_classification
from .long_short_liquidations.long_short_liquidations_classifier import classify_long_short_liquidations
from .on_chain_miners.on_chain_miners_classifier import classify_on_chain_miners
from .etf_exchange_flows import run_etf_exchange_flows_classification


def _run_long_short_liquidations_classification_adapter(processing_contract: Mapping[str, Any], *,
                                                         family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    return classify_long_short_liquidations(processing_contract, **dict(family_arguments))

def _run_on_chain_miners_classification_adapter(processing_contract: Mapping[str, Any], *,
                                                 family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    if family_arguments:
        raise ValueError("on_chain_miners Classification does not accept family arguments")
    return classify_on_chain_miners(processing_contract)

def _run_etf_exchange_flows_classification_adapter(processing_contract: Mapping[str, Any], *,
                                                    family_arguments: Mapping[str, Any]) -> dict[str, Any]:
    return run_etf_exchange_flows_classification(
        processing_contract=processing_contract, **dict(family_arguments)
    )

CLASSIFICATION_FAMILY_HANDLERS = {"prices_ohlcv": run_prices_ohlcv_classification,
                                  "long_short_liquidations": _run_long_short_liquidations_classification_adapter,
                                  "on_chain_miners": _run_on_chain_miners_classification_adapter,
                                  "etf_exchange_flows": _run_etf_exchange_flows_classification_adapter}


def run_classification_pipeline(*, processing_contracts: Mapping[str, Mapping[str, Any]],
                                enabled_families: Sequence[str] = ("prices_ohlcv",),
                                family_arguments: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
    arguments = family_arguments or {}
    outputs = {}
    for family in enabled_families:
        handler = CLASSIFICATION_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No Classification handler registered for family: {family}")
        if family not in processing_contracts:
            raise ValueError(f"Processing contract missing for family: {family}")
        if family == "prices_ohlcv":
            outputs[family] = handler(processing_contracts[family], **dict(arguments.get(family, {})))
        else:
            outputs[family] = handler(processing_contracts[family], family_arguments=dict(arguments.get(family, {})))
    return outputs
