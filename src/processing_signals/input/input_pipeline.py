"""Current Input pipeline orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import Any

from processing_signals.input.extraction import extract_endpoint
from processing_signals.input.normalization import normalize_extracted_raw
from processing_signals.input.union import union_normalized_payloads


DEFAULT_PROVIDERS = ["coinglass", "cryptoquant", "glassnode"]
VALID_PROVIDERS = {"coinglass", "cryptoquant", "glassnode", "external_indices"}


class InputPipeline:
    def __init__(
        self,
        mode: str = "synthetic",
        providers: list[str] | None = None,
        asset: str = "BTC",
        symbol: str = "BTCUSDT",
        output_dir: str | Path = "data/data_input/normalized",
        run_id: str | None = None,
        **kwargs: Any,
    ) -> None:
        self.mode = mode
        self.providers = providers or list(DEFAULT_PROVIDERS)
        self.asset = asset
        self.symbol = symbol
        self.output_dir = Path(output_dir)
        self.run_id = run_id
        self.kwargs = kwargs

    def run(self) -> dict[str, Any]:
        return run_input_pipeline(
            mode=self.mode,
            providers=self.providers,
            asset=self.asset,
            symbol=self.symbol,
            output_dir=self.output_dir,
            run_id=self.run_id,
            **self.kwargs,
        )


def run_input_pipeline(
    *,
    mode: str = "synthetic",
    providers: list[str] | None = None,
    asset: str = "BTC",
    symbol: str = "BTCUSDT",
    output_dir: str | Path = "data/data_input/normalized",
    run_id: str | None = None,
    timeframes: list[str] | None = None,
    extraction_windows: list[str] | None = None,
    min_records: int = 600,
    **_: Any,
) -> dict[str, Any]:
    """Run the Input pipeline."""
    run_id = run_id or datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    selected_providers = providers or list(DEFAULT_PROVIDERS)
    normalized_payloads: list[dict[str, Any]] = []
    provider_status: dict[str, dict[str, Any]] = {}
    unavailable_timeframes: list[dict[str, Any]] = []

    for provider in selected_providers:
        if provider not in VALID_PROVIDERS:
            provider_status[provider] = {"status": "error", "errors": [f"Unknown provider: {provider}"]}
            continue

        endpoints = _load_provider_endpoints(provider)
        skipped_live_external = 0
        skipped_live_missing_path = 0
        live_request_failed = 0
        timeframe_not_available = 0

        for endpoint_config in endpoints:
            for timeframe, extraction_window in _endpoint_iterations(
                endpoint_config,
                timeframes=timeframes,
                extraction_windows=extraction_windows,
            ):
                raw = extract_endpoint(
                    provider=provider,
                    mode=mode,
                    endpoint_config=endpoint_config,
                    run_id=run_id,
                    asset=asset,
                    symbol=symbol,
                    timeframe=timeframe,
                    extraction_window=extraction_window,
                    min_records=min_records,
                )
                if raw["status"] == "skipped_live_external_provider_required":
                    skipped_live_external += 1
                elif raw["status"] == "skipped_live_path_missing":
                    skipped_live_missing_path += 1
                elif raw["status"] == "live_request_failed":
                    live_request_failed += 1
                elif raw["status"] == "timeframe_not_available":
                    timeframe_not_available += 1
                    unavailable_timeframes.append(
                        {
                            "provider": provider,
                            "family": endpoint_config.get("family"),
                            "subtype": endpoint_config.get("subtype"),
                            "requested_timeframe": timeframe,
                            "status": "timeframe_not_available",
                            "reason": raw.get("metadata", {}).get("error", "synthetic timeframe not available"),
                        }
                    )

        normalized = normalize_extracted_raw(provider, run_id)
        normalized_payloads.extend(normalized)
        provider_status[provider] = {
            "status": "ok" if normalized else "skipped",
            "endpoints": len(endpoints),
            "payloads": len(normalized),
            "skipped_live_external_provider_required": skipped_live_external,
            "skipped_live_path_missing": skipped_live_missing_path,
            "live_request_failed": live_request_failed,
            "timeframe_not_available": timeframe_not_available,
        }

    manifest = union_normalized_payloads(
        normalized_payloads,
        run_id,
        output_dir=output_dir,
        unavailable_timeframes=unavailable_timeframes,
    )
    return {
        "status": manifest["status"],
        "run_id": run_id,
        "output_path": str(output_dir),
        "records_total": manifest["records_total"],
        "providers": provider_status,
        "unavailable_timeframes": unavailable_timeframes,
        "manifest_path": str(Path(output_dir) / "manifest.json"),
    }


def _load_provider_endpoints(provider: str) -> list[dict[str, Any]]:
    module_name = "endpoint_registry" if provider == "external_indices" else f"endpoint_registry_{provider}"
    module = import_module(f"processing_signals.input.apis.{provider}.{module_name}")
    return list(getattr(module, "ENDPOINTS"))


def _endpoint_iterations(
    endpoint_config: dict[str, Any],
    timeframes: list[str] | None,
    extraction_windows: list[str] | None,
) -> list[tuple[str | None, str | None]]:
    if endpoint_config.get("supports_timeframe"):
        configured_timeframes = list(endpoint_config.get("synthetic_timeframes") or [])
        if timeframes is not None:
            configured_timeframes = [timeframe for timeframe in configured_timeframes if timeframe in timeframes]
        return [(timeframe, None) for timeframe in configured_timeframes]

    configured_windows = list(endpoint_config.get("extraction_windows") or [])
    if extraction_windows is not None:
        configured_windows = [window for window in configured_windows if window in extraction_windows]
    return [(None, window) for window in configured_windows]


def validate_input_outputs(normalized_dir: str | Path = "data/data_input/normalized") -> dict[str, Any]:
    """Validate normalized Input outputs without requiring archive output."""
    import json

    normalized_root = Path(normalized_dir)
    manifest = normalized_root / "manifest.json"
    errors: list[str] = []

    if not normalized_root.exists():
        errors.append(f"Missing normalized directory: {normalized_root}")

    if not manifest.exists():
        errors.append(f"Missing manifest: {manifest}")

    required_keys = {
        "schema_version",
        "provider",
        "family",
        "subtype",
        "data_type",
        "asset",
        "symbol",
        "timeframe",
        "extraction_window",
        "records",
        "metadata",
        "quality",
    }

    for path in sorted(normalized_root.glob("*/*.json")):
        if path.name == "manifest.json":
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"{path}: invalid JSON: {exc}")
            continue

        missing = required_keys - set(payload.keys())
        if missing:
            errors.append(f"{path}: missing keys {sorted(missing)}")

        records = payload.get("records", [])
        if not isinstance(records, list):
            errors.append(f"{path}: records must be a list")
            continue

        timestamps = [
            row.get("timestamp")
            for row in records
            if isinstance(row, dict) and row.get("timestamp") is not None
        ]

        if timestamps and timestamps != sorted(timestamps):
            errors.append(f"{path}: timestamps are not sorted")

        if timestamps and len(timestamps) != len(set(timestamps)):
            errors.append(f"{path}: duplicate timestamps found")

        min_required = int(payload.get("quality", {}).get("min_records_required", 0) or 0)
        data_type = payload.get("data_type")

        if data_type in {"candlestick", "candlestick_derived", "bars", "time_series"}:
            if min_required and len(records) < min_required:
                errors.append(f"{path}: records below minimum {len(records)} < {min_required}")

        if data_type in {"snapshot", "event_list", "heatmap", "matrix"}:
            if payload.get("timeframe") is not None:
                errors.append(f"{path}: non-timeframe data_type has timeframe != None")
            if payload.get("extraction_window") is None:
                errors.append(f"{path}: non-timeframe data_type missing extraction_window")

    return {
        "status": "ok" if not errors else "error",
        "errors": errors,
    }
