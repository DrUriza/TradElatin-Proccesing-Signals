"""Long/Short Liquidations Input -> Processing -> Classification -> screen vertical."""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import time
from typing import Any

from processing_signals.classification.classification_pipeline import run_classification_pipeline
from processing_signals.classification.long_short_liquidations.long_short_liquidations_contract_builder import build_long_short_liquidations_contract
from processing_signals.input.input_pipeline import run_input_pipeline
from processing_signals.processing.processing_pipeline import run_processing_pipeline


def _execution_timestamp(value: int | None) -> int:
    timestamp = int(time.time()) if value is None else value
    if type(timestamp) is not int or timestamp <= 0:
        raise ValueError("now_timestamp must be a positive integer")
    return timestamp


def run_long_short_liquidations_vertical(
    *, fetcher: Any, input_arguments: Mapping[str, Any] | None = None,
    processing_arguments: Mapping[str, Any] | None = None,
    classification_arguments: Mapping[str, Any] | None = None,
    contract_arguments: Mapping[str, Any] | None = None,
    previous_state: Mapping[str, Any] | None = None, now_timestamp: int | None = None,
    runtime_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    timestamp = _execution_timestamp(now_timestamp)
    previous = deepcopy(dict(previous_state or {}))
    input_args = deepcopy(dict(input_arguments or {}))
    processing_args = deepcopy(dict(processing_arguments or {}))
    classification_args = deepcopy(dict(classification_arguments or {}))
    contract_args = deepcopy(dict(contract_arguments or {}))
    metadata = deepcopy(dict(runtime_metadata or {}))
    input_args["fetcher"] = fetcher
    input_args.setdefault("reference_timestamp", timestamp)
    input_args.setdefault("clock", lambda: timestamp)
    if "existing_contract" not in input_args and isinstance(previous.get("input"), Mapping):
        input_args["existing_contract"] = deepcopy(previous["input"])
    input_output = run_input_pipeline(enabled_families=("long_short_liquidations",),
        family_arguments={"long_short_liquidations": input_args})["long_short_liquidations"]
    processing_output = run_processing_pipeline(input_contracts={"long_short_liquidations": input_output},
        enabled_families=("long_short_liquidations",), now_timestamp=timestamp,
        family_arguments={"long_short_liquidations": processing_args})["long_short_liquidations"]
    classification_output = run_classification_pipeline(processing_contracts={"long_short_liquidations": processing_output},
        enabled_families=("long_short_liquidations",),
        family_arguments={"long_short_liquidations": classification_args})["long_short_liquidations"]
    context = contract_args.pop("context", metadata.pop("context", None))
    if not isinstance(context, Mapping):
        raise ValueError("contract context is required")
    runtime = contract_args.pop("runtime_context", None)
    if runtime is None:
        runtime = {"generated_at": timestamp, "updated_at": metadata.pop("updated_at", timestamp),
                   "data_mode": metadata.pop("data_mode", "live"), "is_demo": metadata.pop("is_demo", False),
                   "cache_status": metadata.pop("cache_status", "unknown"), **metadata}
    screen = build_long_short_liquidations_contract(processing_output, classification_output,
        context=context, runtime_context=runtime, **contract_args)
    return {"input": input_output, "processing": processing_output,
            "classification": classification_output, "screen": screen}
