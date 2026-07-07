"""Helpers for provider endpoint registries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


LEGACY_SYNTHETIC_FAMILY_ALIASES = {
    "cvd_volume_orderflow": "volume_orderflow",
    "open_interest_and_funding": "derivatives_open_interest",
    "onchain_miners": "on_chain_miners",
}


def endpoint(
    *,
    provider: str,
    family: str,
    subtype: str,
    path: str | None,
    coverage_role: str,
    live_status: str,
    data_type: str = "time_series",
    supports_timeframe: bool = True,
    synthetic_status: str = "supported",
    response_shape: str | None = None,
    live_supported_timeframes: list[str] | None = None,
    synthetic_timeframes: list[str] | None = None,
    extraction_windows: list[str] | None = None,
    default_params: dict[str, Any] | None = None,
    notes: str = "",
    external_provider: str | None = None,
) -> dict[str, Any]:
    if path is None and live_status in {"supported"}:
        raise ValueError(f"{provider}/{family}/{subtype} is supported but has no live path")

    synthetic_timeframes = list(synthetic_timeframes or [])
    if synthetic_status == "skip" or not supports_timeframe:
        synthetic_timeframes = []

    if extraction_windows is None:
        if data_type == "snapshot":
            extraction_windows = ["latest"]
        elif data_type in {"event_list", "heatmap"}:
            extraction_windows = ["24h"]
        else:
            extraction_windows = []

    template = None
    if synthetic_status != "skip":
        slot = "timeframe" if supports_timeframe else "extraction_window"
        template = f"{family}/{subtype}/{{{slot}}}_raw.json"

    item = {
        "provider": provider,
        "family": family,
        "subtype": subtype,
        "endpoint_name": f"{provider}_{family}_{subtype}",
        "path": path,
        "method": "GET" if path else None,
        "coverage_role": coverage_role,
        "live_status": live_status,
        "synthetic_status": synthetic_status,
        "data_type": data_type,
        "supports_timeframe": supports_timeframe,
        "live_supported_timeframes": list(live_supported_timeframes or []),
        "synthetic_timeframes": synthetic_timeframes,
        "extraction_windows": list(extraction_windows),
        "response_shape": response_shape or provider,
        "synthetic_file_template": template,
        "default_params": dict(default_params or {}),
        "notes": notes,
    }
    if external_provider:
        item["external_provider"] = external_provider
    return item


def load_json_endpoint_registry(provider: str, json_path: str | Path) -> list[dict[str, Any]]:
    """Load a provider JSON endpoint contract into the pipeline registry shape."""
    contract = json.loads(Path(json_path).read_text(encoding="utf-8"))
    endpoints: list[dict[str, Any]] = []

    for source in contract.get("endpoints", []):
        family = str(source["family"])
        raw_family = LEGACY_SYNTHETIC_FAMILY_ALIASES.get(family, family)
        subtype = str(source["endpoint_id"])
        slots = _source_slots(source)
        data_type = _data_type(source)
        supports_timeframe = data_type != "matrix" and source.get("extraction_mode") in {
            "timeframe_window",
            "provider_interval",
            "provider_window",
        }
        slot_name = "timeframe" if supports_timeframe else "extraction_window"

        item = endpoint(
            provider=provider,
            family=family,
            subtype=subtype,
            path=source.get("live_path"),
            coverage_role=str(source.get("coverage_role") or "primary"),
            live_status="supported" if source.get("live_path") else "not_available",
            data_type=data_type,
            supports_timeframe=supports_timeframe,
            live_supported_timeframes=slots if supports_timeframe else [],
            synthetic_timeframes=slots if supports_timeframe else [],
            extraction_windows=[] if supports_timeframe else slots,
            default_params={},
            notes=str(source.get("notes") or contract.get("principle") or ""),
        )
        item["synthetic_file_template"] = f"{provider}/{family}/{subtype}/{{{slot_name}}}_raw.json"
        item["raw_family"] = raw_family
        item["raw_shape"] = source.get("raw_shape")
        item["loader_strategy"] = _loader_strategy(source, data_type)
        item["row_timestamp_required"] = data_type in {"candlestick", "time_series"}
        item["min_records"] = int(source.get("min_records") or 1)
        endpoints.append(item)

    return endpoints


def _source_slots(source: dict[str, Any]) -> list[str]:
    return list(source.get("timeframes") or source.get("intervals") or source.get("windows") or [])


def _data_type(source: dict[str, Any]) -> str:
    subtype = str(source.get("endpoint_id") or "")
    raw_shape = str(source.get("raw_shape") or "")
    extraction_mode = str(source.get("extraction_mode") or "")

    if "ohlcv" in raw_shape or "ohlc" in raw_shape:
        return "candlestick"
    if "matrix" in raw_shape:
        return "matrix"
    if "heatmap" in subtype or "heatmap" in raw_shape:
        return "heatmap"
    if extraction_mode in {"timeframe_window", "provider_interval", "provider_window"}:
        return "time_series"
    if any(token in subtype for token in ("events", "large_trades", "orders")):
        return "event_list"
    if any(token in subtype for token in ("latest", "map", "max_pain")):
        return "snapshot"
    return "time_series"


def _loader_strategy(source: dict[str, Any], data_type: str) -> str:
    raw_shape = str(source.get("raw_shape") or "")
    if data_type == "matrix":
        return "matrix_fixed_window"
    if data_type == "heatmap":
        return "heatmap_fixed_window"
    if data_type == "snapshot":
        return "snapshot_fixed_window"
    if data_type == "event_list":
        return "event_list_fixed_window"
    if "ohlcv" in raw_shape or "ohlc" in raw_shape:
        return "candlestick_timeframe"
    return "time_series"
