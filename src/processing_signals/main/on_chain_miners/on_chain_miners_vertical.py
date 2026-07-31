"""On-chain Miners Input -> Processing -> Classification -> screen vertical."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import time
from typing import Any

from processing_signals.classification.classification_pipeline import run_classification_pipeline
from processing_signals.classification.on_chain_miners.on_chain_miners_contract_builder import build_on_chain_miners_screen_contract
from processing_signals.input.input_pipeline import run_input_pipeline
from processing_signals.processing.processing_pipeline import run_processing_pipeline


def _execution_timestamp(value: int | None) -> int:
    timestamp = int(time.time()) if value is None else value
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("now_timestamp must be a positive integer")
    return timestamp


def run_on_chain_miners_vertical(
    *, fetcher: Any, input_arguments: Mapping[str, Any] | None = None,
    processing_arguments: Mapping[str, Any] | None = None,
    classification_arguments: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None,
    now_timestamp: int | None = None,
) -> dict[str, Any]:
    """Run the canonical family without mutating arguments or previous state."""
    timestamp = _execution_timestamp(now_timestamp)
    previous = deepcopy(dict(previous_state or {}))
    input_args = deepcopy(dict(input_arguments or {}))
    processing_args = deepcopy(dict(processing_arguments or {}))
    classification_args = deepcopy(dict(classification_arguments or {}))
    input_args["fetcher"] = fetcher
    input_args.setdefault("reference_timestamp", timestamp)
    input_args.setdefault("execution_timestamp", timestamp)
    if "existing_contract" not in input_args and isinstance(previous.get("input"), Mapping):
        input_args["existing_contract"] = deepcopy(previous["input"])

    input_output = run_input_pipeline(
        enabled_families=("on_chain_miners",),
        family_arguments={"on_chain_miners": input_args},
    )["on_chain_miners"]
    processing_output = run_processing_pipeline(
        input_contracts={"on_chain_miners": input_output},
        enabled_families=("on_chain_miners",),
        existing_processing={"on_chain_miners": deepcopy(previous["processing"])}
        if isinstance(previous.get("processing"), Mapping) else None,
        now_timestamp=timestamp,
        family_arguments={"on_chain_miners": processing_args},
    )["on_chain_miners"]
    classification_output = run_classification_pipeline(
        processing_contracts={"on_chain_miners": processing_output},
        enabled_families=("on_chain_miners",),
        family_arguments={"on_chain_miners": classification_args},
    )["on_chain_miners"]
    screen = build_on_chain_miners_screen_contract(processing_output, classification_output)
    return {"input": input_output, "processing": processing_output,
            "classification": classification_output, "screen": screen}
