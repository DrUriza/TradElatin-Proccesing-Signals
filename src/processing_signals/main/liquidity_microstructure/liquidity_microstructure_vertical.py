"""End-to-end Liquidity Microstructure vertical and atomic screen exporter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract
from processing_signals.input.liquidity_microstructure.liquidity_microstructure_data_raw_preprocessing import run_liquidity_microstructure_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


class LiquidityMicrostructureVerticalError(RuntimeError):
    def __init__(self, stage: str, reason: str, details: str | None = None) -> None:
        self.stage, self.reason, self.details = stage, reason, details
        super().__init__(f"{stage}:{reason}" + (f":{details}" if details else ""))


def export_liquidity_microstructure_screen_contract(screen_contract: Mapping[str, Any], destination: str | Path) -> dict[str, Any]:
    if not isinstance(screen_contract, Mapping) or screen_contract.get("schema", {}).get("id") != "trad_elatin.liquidity_microstructure.screen.v1" or screen_contract.get("stage") != "screen_contract":
        raise LiquidityMicrostructureVerticalError("export", "invalid_screen_contract")
    quality = screen_contract.get("quality", {}).get("status")
    if quality == "invalid":
        raise LiquidityMicrostructureVerticalError("export", "invalid_screen_contract")
    path = Path(destination)
    try:
        serialized = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
        payload = serialized.encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, path)
        finally:
            if os.path.exists(temporary_name):
                os.unlink(temporary_name)
        return {"status": "exported_partial" if quality == "partial" else "exported", "path": str(path), "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(), "atomic": True, "temporary_path_removed": True,
                "quality_status": quality, "error": None}
    except LiquidityMicrostructureVerticalError:
        raise
    except Exception as exc:
        raise LiquidityMicrostructureVerticalError("export", "export_failed", type(exc).__name__) from exc


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise LiquidityMicrostructureVerticalError("arguments", "invalid_arguments", name)
    return deepcopy(dict(value))


def run_liquidity_microstructure_vertical(*, fetcher: Any, mode: str = "bootstrap", existing_input: Mapping[str, Any] | None = None,
                                          existing_processing: Mapping[str, Any] | None = None, recovery_requests: Sequence[Any] | None = None,
                                          input_arguments: Mapping[str, Any] | None = None, processing_arguments: Mapping[str, Any] | None = None,
                                          classification_arguments: Mapping[str, Any] | None = None, builder_arguments: Mapping[str, Any] | None = None,
                                          runtime_context: Mapping[str, Any], selected_market: str = "perpetual", selected_timeframe: str = "1m",
                                          export_path: str | Path | None = None, debug_raw: bool = False,
                                          previous_state: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if fetcher is None:
        raise LiquidityMicrostructureVerticalError("input", "live_transport_not_configured")
    if mode not in {"bootstrap", "incremental", "recovery"} or not isinstance(runtime_context, Mapping):
        raise LiquidityMicrostructureVerticalError("arguments", "invalid_arguments")
    if runtime_context.get("data_mode") == "live" and runtime_context.get("is_demo") is not False:
        raise LiquidityMicrostructureVerticalError("arguments", "invalid_runtime_context")
    if previous_state:
        existing_input = existing_input or previous_state.get("input")
        existing_processing = existing_processing or previous_state.get("processing")
    ia, pa, ca, ba = (_mapping(input_arguments, "input_arguments"), _mapping(processing_arguments, "processing_arguments"),
                      _mapping(classification_arguments, "classification_arguments"), _mapping(builder_arguments, "builder_arguments"))
    ia.update({"fetcher": fetcher, "requested_mode": mode, "existing_contract": deepcopy(existing_input), "recovery_requests": deepcopy(recovery_requests),
               "debug_raw": debug_raw, "data_mode": runtime_context.get("data_mode"), "is_demo": runtime_context.get("is_demo")})
    try:
        input_contract = run_liquidity_microstructure_input(**ia)
    except Exception as exc:
        raise LiquidityMicrostructureVerticalError("input", "input_failed", type(exc).__name__) from exc
    try:
        processing_contract = process_liquidity_microstructure(input_contract, existing_processing=deepcopy(existing_processing), **pa)
    except Exception as exc:
        raise LiquidityMicrostructureVerticalError("processing", "processing_failed", type(exc).__name__) from exc
    try:
        classification_contract = classify_liquidity_microstructure(processing_contract, **ca)
    except Exception as exc:
        raise LiquidityMicrostructureVerticalError("classification", "classification_failed", type(exc).__name__) from exc
    try:
        screen_contract = build_liquidity_microstructure_screen_contract({"processing": processing_contract, "classification": classification_contract},
                                                                          runtime_context=deepcopy(runtime_context), selected_market=selected_market,
                                                                          selected_timeframe=selected_timeframe, **ba)
    except Exception as exc:
        raise LiquidityMicrostructureVerticalError("builder", "builder_failed", type(exc).__name__) from exc
    if screen_contract.get("quality", {}).get("status") == "invalid":
        raise LiquidityMicrostructureVerticalError("builder", "invalid_screen_contract")
    export = ({"status": "not_requested", "path": None, "bytes": None, "sha256": None, "atomic": True,
               "temporary_path_removed": True, "quality_status": screen_contract["quality"]["status"], "error": None}
              if export_path is None else export_liquidity_microstructure_screen_contract(screen_contract, export_path))
    statuses = (input_contract["quality"]["status"], processing_contract["quality"]["status"], classification_contract["quality"]["status"], screen_contract["quality"]["status"])
    quality = "invalid" if "invalid" in statuses or export["status"] == "failed" else "partial" if "partial" in statuses else "ok"
    return {"family": "liquidity_microstructure", "stage": "vertical", "mode": mode, "input": deepcopy(input_contract),
            "processing": deepcopy(processing_contract), "classification": deepcopy(classification_contract), "screen_contract": deepcopy(screen_contract),
            "export": export, "quality": {"status": quality, "input_status": statuses[0], "processing_status": statuses[1],
                                             "classification_status": statuses[2], "screen_status": statuses[3], "export_status": export["status"],
                                             "warnings": [], "errors": [], "data_as_of": screen_contract.get("quality", {}).get("data_as_of")}}


class LiquidityMicrostructureVertical:
    def __init__(self, **arguments: Any) -> None:
        self.arguments = deepcopy(arguments)

    def run(self, **arguments: Any) -> dict[str, Any]:
        return run_liquidity_microstructure_vertical(**{**deepcopy(self.arguments), **deepcopy(arguments)})
