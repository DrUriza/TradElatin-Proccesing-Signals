"""Extract raw endpoint payloads from live or synthetic sources."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URLS = {
    "coinglass": "https://open-api-v4.coinglass.com",
    "cryptoquant": "https://api.cryptoquant.com/v1",
    "glassnode": "https://api.glassnode.com/v1",
}


def prepare_extraction_context(provider: str, mode: str, endpoint_config: dict[str, Any]) -> dict[str, Any]:
    """Prepare synthetic or live extraction context."""
    if mode not in {"synthetic", "live"}:
        raise ValueError(f"Unsupported input mode: {mode}")

    context = {
        "provider": provider,
        "mode": mode,
        "base_url": endpoint_config.get("base_url") or BASE_URLS.get(provider),
        "path": endpoint_config.get("path"),
        "headers": {},
        "api_key": None,
        "callable_live": mode == "live"
        and endpoint_config.get("path") is not None
        and endpoint_config.get("live_status") != "external_provider_required",
    }
    if mode == "live":
        api_key = _api_key(provider)
        context["api_key"] = api_key
        context["headers"] = _headers(provider, api_key)
    return context


def extract_endpoint(
    *,
    provider: str,
    mode: str,
    endpoint_config: dict[str, Any],
    run_id: str,
    asset: str,
    symbol: str,
    timeframe: str | None = None,
    extraction_window: str | None = None,
    min_records: int = 200,
) -> dict[str, Any]:
    """Extract one endpoint into a raw payload descriptor."""
    context = prepare_extraction_context(provider, mode, endpoint_config)
    folder_provider = str(context["provider"])
    effective_min_records = int(endpoint_config.get("min_records") or min_records)

    if mode == "live" and not context["callable_live"]:
        raw = {
            "run_id": run_id,
            "provider": endpoint_config["provider"],
            "mode": mode,
            "endpoint_name": endpoint_config["endpoint_name"],
            "family": endpoint_config["family"],
            "subtype": endpoint_config["subtype"],
            "data_type": endpoint_config["data_type"],
            "asset": asset,
            "symbol": symbol,
            "exchange": _exchange(endpoint_config),
            "timeframe": timeframe,
            "extraction_window": extraction_window,
            "status": "skipped_live_external_provider_required"
            if endpoint_config.get("live_status") == "external_provider_required"
            else "skipped_live_path_missing",
            "raw_response": None,
            "metadata": {
                "reason": "not callable in live mode",
                "base_url": context.get("base_url"),
                "path": context.get("path"),
                "headers": _redact_headers(context.get("headers", {})),
                "min_records": effective_min_records,
                "raw_shape": endpoint_config.get("raw_shape"),
                "loader_strategy": endpoint_config.get("loader_strategy"),
                "row_timestamp_required": endpoint_config.get("row_timestamp_required"),
            },
        }
        _write_raw(folder_provider, raw)
        return raw

    raw_response = None
    if mode == "synthetic":
        try:
            raw_response = _load_synthetic_raw_response(folder_provider, endpoint_config, timeframe, extraction_window)
        except FileNotFoundError as exc:
            status = "timeframe_not_available" if timeframe is not None else "synthetic_raw_missing"
            raw = {
                "run_id": run_id,
                "provider": endpoint_config["provider"],
                "mode": mode,
                "endpoint_name": endpoint_config["endpoint_name"],
                "family": endpoint_config["family"],
                "subtype": endpoint_config["subtype"],
                "data_type": endpoint_config["data_type"],
                "asset": asset,
                "symbol": symbol,
                "exchange": _exchange(endpoint_config),
                "timeframe": timeframe,
                "extraction_window": extraction_window,
                "status": status,
                "raw_response": None,
                "metadata": {
                    "mode": mode,
                    "path": endpoint_config.get("path"),
                    "live_status": endpoint_config.get("live_status"),
                    "requested_timeframe": timeframe,
                    "requested_extraction_window": extraction_window,
                    "error": str(exc),
                    "min_records": effective_min_records,
                    "raw_shape": endpoint_config.get("raw_shape"),
                    "loader_strategy": endpoint_config.get("loader_strategy"),
                    "row_timestamp_required": endpoint_config.get("row_timestamp_required"),
                },
            }
            _write_raw(folder_provider, raw)
            return raw
    else:
        try:
            raw_response = _load_live_raw_response(
                context=context,
                endpoint_config=endpoint_config,
                asset=asset,
                symbol=symbol,
                timeframe=timeframe,
                extraction_window=extraction_window,
            )
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            raw = {
                "run_id": run_id,
                "provider": endpoint_config["provider"],
                "mode": mode,
                "endpoint_name": endpoint_config["endpoint_name"],
                "family": endpoint_config["family"],
                "subtype": endpoint_config["subtype"],
                "data_type": endpoint_config["data_type"],
                "asset": asset,
                "symbol": symbol,
                "exchange": _exchange(endpoint_config),
                "timeframe": timeframe,
                "extraction_window": extraction_window,
                "status": "live_request_failed",
                "raw_response": None,
                "metadata": {
                    "error": str(exc),
                    "base_url": context.get("base_url"),
                    "path": context.get("path"),
                    "headers": _redact_headers(context.get("headers", {})),
                    "api_key_configured": bool(context.get("api_key")),
                    "min_records": effective_min_records,
                    "raw_shape": endpoint_config.get("raw_shape"),
                    "loader_strategy": endpoint_config.get("loader_strategy"),
                    "row_timestamp_required": endpoint_config.get("row_timestamp_required"),
                },
            }
            _write_raw(folder_provider, raw)
            return raw

    raw = {
        "run_id": run_id,
        "provider": endpoint_config["provider"],
        "mode": mode,
        "endpoint_name": endpoint_config["endpoint_name"],
        "family": endpoint_config["family"],
        "subtype": endpoint_config["subtype"],
        "data_type": endpoint_config["data_type"],
        "asset": asset,
        "symbol": symbol,
        "exchange": _exchange(endpoint_config),
        "timeframe": timeframe,
        "extraction_window": extraction_window,
        "status": "ok",
        "raw_response": raw_response,
        "metadata": {
            "mode": mode,
            "path": endpoint_config.get("path"),
            "live_status": endpoint_config.get("live_status"),
            "base_url": context.get("base_url"),
            "headers": _redact_headers(context.get("headers", {})),
            "api_key_configured": bool(context.get("api_key")),
            "min_records": effective_min_records,
            "raw_shape": endpoint_config.get("raw_shape"),
            "loader_strategy": endpoint_config.get("loader_strategy"),
            "row_timestamp_required": endpoint_config.get("row_timestamp_required"),
        },
    }
    _write_raw(folder_provider, raw)
    return raw


def _load_synthetic_raw_response(
    folder_provider: str,
    endpoint_config: dict[str, Any],
    timeframe: str | None,
    extraction_window: str | None,
) -> Any | None:
    slot = timeframe or extraction_window or "latest"
    zip_root = Path(__file__).resolve().parent / "apis" / folder_provider / "synthetic_raw"
    zip_path = zip_root / f"{folder_provider}_synthetic_raw.zip"
    if not zip_path.exists():
        corrected_zip_path = zip_root / f"{folder_provider}_synthetic_raw_corrected.zip"
        if corrected_zip_path.exists():
            zip_path = corrected_zip_path
    if not zip_path.exists():
        raise FileNotFoundError(f"Missing synthetic raw ZIP: {zip_path}")

    template = endpoint_config.get("synthetic_file_template")
    if template:
        requested_member = str(template).format(timeframe=timeframe, extraction_window=extraction_window, slot=slot)
    else:
        requested_member = f"{endpoint_config['family']}/{endpoint_config['subtype']}/{slot}_raw.json"

    with zipfile.ZipFile(zip_path, "r") as archive:
        try:
            return json.loads(archive.read(requested_member).decode("utf-8"))
        except KeyError as exc:
            fallback_member = f"{folder_provider}/{requested_member}"
            try:
                return json.loads(archive.read(fallback_member).decode("utf-8"))
            except KeyError:
                raise FileNotFoundError(f"Missing synthetic raw member {requested_member} in {zip_path}") from exc


def _load_live_raw_response(
    *,
    context: dict[str, Any],
    endpoint_config: dict[str, Any],
    asset: str,
    symbol: str,
    timeframe: str | None,
    extraction_window: str | None,
) -> Any:
    base_url = context.get("base_url")
    path = context.get("path")
    if not base_url or not path:
        raise ValueError("Live endpoint requires base_url and path")

    params = _request_params(endpoint_config, asset, symbol, timeframe, extraction_window)
    query = urlencode(params)
    url = f"{str(base_url).rstrip('/')}/{str(path).lstrip('/')}"
    if query:
        url = f"{url}?{query}"

    request = Request(
        url,
        headers={str(key): str(value) for key, value in context.get("headers", {}).items()},
        method=str(endpoint_config.get("method") or "GET"),
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    return json.loads(body) if body else None


def _write_raw(folder_provider: str, raw: dict[str, Any]) -> Path:
    slot = raw.get("timeframe") or raw.get("extraction_window") or "latest"
    root = (
        Path(__file__).resolve().parent
        / "apis"
        / folder_provider
        / "extracted_raw"
        / str(raw["run_id"])
        / str(raw["family"])
        / str(raw["subtype"])
    )
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{slot}_raw.json"
    path.write_text(json.dumps(raw, ensure_ascii=True, indent=2), encoding="utf-8")
    return path


def _exchange(endpoint_config: dict[str, Any]) -> str | None:
    params = endpoint_config.get("default_params") or {}
    exchange = params.get("exchange")
    return str(exchange) if exchange is not None else None


def _request_params(
    endpoint_config: dict[str, Any],
    asset: str,
    symbol: str,
    timeframe: str | None,
    extraction_window: str | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for key, value in (endpoint_config.get("default_params") or {}).items():
        if isinstance(value, str):
            value = (
                value.replace("{timeframe}", timeframe or "")
                .replace("{asset}", asset)
                .replace("{symbol}", symbol)
                .replace("{extraction_window}", extraction_window or "")
            )
        params[key] = value

    params.setdefault("symbol", symbol)
    if timeframe is not None:
        params.setdefault("interval", timeframe)
    if extraction_window is not None:
        params.setdefault("window", extraction_window)
    return {key: value for key, value in params.items() if value is not None and value != ""}


def _api_key(provider: str) -> str | None:
    names = [
        f"{provider.upper()}_API_KEY",
        f"{provider.upper().replace('-', '_')}_API_KEY",
        "INPUT_API_KEY",
    ]
    env_file_values = _load_env_example_values()
    for name in names:
        value = os.getenv(name) or env_file_values.get(name)
        if value:
            return value
    return None


def _load_env_example_values() -> dict[str, str]:
    path = Path(__file__).resolve().parents[3] / ".env.example"
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and value and value.lower() not in {"xxx", "your_api_key", "changeme"}:
            values[key] = value
    return values


def _headers(provider: str, api_key: str | None) -> dict[str, str]:
    headers = {"accept": "application/json"}
    if not api_key:
        return headers
    if provider == "coinglass":
        headers["CG-API-KEY"] = api_key
    else:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(headers)
    for key in redacted:
        if "key" in key.lower() or key.lower() == "authorization":
            redacted[key] = "***"
    return redacted
