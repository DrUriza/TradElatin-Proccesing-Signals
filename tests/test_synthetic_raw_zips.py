"""Generate provider-shaped synthetic raw ZIP files for Input."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import zipfile
from datetime import UTC, datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import Any


SRC_ROOT = Path(__file__).resolve().parents[2]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


PROVIDERS = ("coinglass", "cryptoquant", "glassnode", "external_indices")
SYNTHETIC_TIMEFRAMES = ("1m", "5m", "15m", "1h")
TIMEFRAME_DATA_TYPES = {"candlestick", "candlestick_derived", "bars", "time_series"}
WINDOW_DATA_TYPES = {"snapshot", "event_list", "heatmap"}
BASE_TS = 1_782_777_600


def generate_all_synthetic_raw_zips(providers: tuple[str, ...] = PROVIDERS) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for provider in providers:
        results[provider] = generate_provider_synthetic_raw_zip(provider)
    return results


def generate_provider_synthetic_raw_zip(provider: str) -> dict[str, Any]:
    endpoints = _load_endpoints(provider)
    output_dir = Path(__file__).resolve().parent / "apis" / provider / "synthetic_raw"
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"{provider}_synthetic_raw.zip"

    with tempfile.TemporaryDirectory(prefix=f"{provider}_", dir=output_dir) as tmp:
        tmp_root = Path(tmp)
        files = _write_provider_raw_files(provider, endpoints, tmp_root)
        _write_zip(tmp_root, zip_path)

    validation = validate_synthetic_raw_zip(provider, zip_path, endpoints)
    return {
        "provider": provider,
        "zip_path": str(zip_path),
        "files": len(files),
        "validation": validation,
    }


def validate_synthetic_raw_zip(provider: str, zip_path: str | Path, endpoints: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    zip_file = Path(zip_path)
    errors: list[str] = []
    if not zip_file.exists():
        return {"status": "error", "errors": [f"Missing ZIP: {zip_file}"], "files": 0}

    endpoint_by_member = _expected_members(endpoints or _load_endpoints(provider))
    files = 0
    with zipfile.ZipFile(zip_file, "r") as archive:
        names = [name for name in archive.namelist() if name.endswith(".json")]
        for name in names:
            files += 1
            try:
                payload = json.loads(archive.read(name).decode("utf-8"))
            except json.JSONDecodeError as exc:
                errors.append(f"{name}: invalid JSON: {exc}")
                continue

            endpoint = endpoint_by_member.get(name)
            if endpoint is None:
                errors.append(f"{name}: no matching endpoint")
                continue
            errors.extend(_validate_payload_shape(provider, endpoint, name, payload))

    missing = sorted(set(endpoint_by_member) - set(names))
    errors.extend(f"{name}: missing from ZIP" for name in missing)
    return {"status": "ok" if not errors else "error", "errors": errors, "files": files}


def _write_provider_raw_files(provider: str, endpoints: list[dict[str, Any]], root: Path) -> list[Path]:
    files: list[Path] = []
    for endpoint in endpoints:
        for slot, records in _records_for_endpoint(provider, endpoint):
            relative = Path(endpoint["family"]) / endpoint["subtype"] / f"{slot}_raw.json"
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = _provider_payload(provider, endpoint, slot, records)
            path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            files.append(path)
    return files


def _records_for_endpoint(provider: str, endpoint: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    data_type = endpoint.get("data_type")
    if endpoint.get("supports_timeframe"):
        return [
            (timeframe, _timeframe_records(provider, endpoint, timeframe, 600))
            for timeframe in SYNTHETIC_TIMEFRAMES
        ]

    windows = endpoint.get("extraction_windows") or ["latest"]
    output: list[tuple[str, list[dict[str, Any]]]] = []
    for window in windows:
        if data_type == "snapshot":
            count = 10
        elif data_type == "heatmap":
            count = 180
        else:
            count = 120
        output.append((str(window), _window_records(provider, endpoint, str(window), count)))
    return output


def _provider_payload(provider: str, endpoint: dict[str, Any], slot: str, records: list[dict[str, Any]]) -> Any:
    if provider == "coinglass":
        return {"code": "0", "msg": "success", "data": records}
    if provider == "cryptoquant":
        return {"status": {"code": 200, "message": "success"}, "result": {"window": _cryptoquant_window(slot), "data": records}}
    if provider == "glassnode":
        return records
    if provider == "external_indices":
        return {"provider": endpoint["provider"], "index": endpoint["subtype"], "data": records}
    return {"data": records}


def _timeframe_records(provider: str, endpoint: dict[str, Any], timeframe: str, count: int) -> list[dict[str, Any]]:
    step = _timeframe_seconds(timeframe)
    base = _base_value(endpoint)
    start = BASE_TS - (count - 1) * step
    data_type = endpoint.get("data_type")

    if provider == "coinglass" and data_type in {"candlestick", "candlestick_derived", "bars"}:
        return [
            {
                "time": (start + index * step) * 1000,
                "open": round(base + index * 0.05, 6),
                "high": round(base + index * 0.05 + 150.0, 6),
                "low": round(base + index * 0.05 - 80.0, 6),
                "close": round(base + index * 0.05 + 35.0, 6),
                "volume": round(1000.0 + index * 1.7, 6),
                "volume_usd": round((1000.0 + index * 1.7) * (base + index * 0.05), 6),
            }
            for index in range(count)
        ]

    if provider == "coinglass":
        return [{"time": (start + index * step) * 1000, "value": round(base + index * 0.03, 6)} for index in range(count)]

    if provider == "cryptoquant":
        return [_cryptoquant_record(endpoint, start + index * step, base + index * 0.03, index) for index in range(count)]

    if provider == "glassnode":
        return [_glassnode_record(endpoint, start + index * step, base + index * 0.03, index) for index in range(count)]

    if provider == "external_indices":
        return [{"timestamp": start + index * step, "value": round(base + index * 0.01, 6)} for index in range(count)]

    return [{"timestamp": start + index * step, "value": round(base + index * 0.03, 6)} for index in range(count)]


def _window_records(provider: str, endpoint: dict[str, Any], window: str, count: int) -> list[dict[str, Any]]:
    base = _base_value(endpoint)
    subtype = endpoint["subtype"]
    data_type = endpoint.get("data_type")

    if provider == "coinglass":
        if data_type == "heatmap":
            return [
                {
                    "time": (BASE_TS + index * 60) * 1000,
                    "price_level": round(58_000.0 + index * 25.0, 2),
                    "liquidation_usd": round(1_000_000.0 + index * 15_000.0, 2),
                    "side": "long" if index % 2 == 0 else "short",
                }
                for index in range(count)
            ]
        if data_type == "event_list":
            return [
                {
                    "time": (BASE_TS + index * 60) * 1000,
                    "exchange": "Binance",
                    "symbol": "BTCUSDT",
                    "side": "bid" if index % 2 == 0 else "ask",
                    "price": round(61_000.0 + index * 3.5, 2),
                    "amount": round(5.0 + index * 0.15, 6),
                    "notional_usd": round((61_000.0 + index * 3.5) * (5.0 + index * 0.15), 2),
                }
                for index in range(count)
            ]
        return [{"time": BASE_TS * 1000, "value": round(base, 6), "window": window}]

    if provider == "glassnode" and subtype == "gamma_exposure":
        return [
            {
                "t": BASE_TS,
                "v": [
                    {"strike": 58_000 + index * 500, "gamma_exposure": round(-1_250_000.0 + index * 65_000.0, 2)}
                    for index in range(20)
                ],
            }
        ]

    if provider == "glassnode":
        return [{"t": BASE_TS + index * 60, "v": round(base + index * 0.05, 6)} for index in range(count)]

    return [{"timestamp": BASE_TS + index * 60, "value": round(base + index * 0.05, 6), "window": window} for index in range(count)]


def _cryptoquant_record(endpoint: dict[str, Any], timestamp: int, value: float, index: int) -> dict[str, Any]:
    subtype = endpoint["subtype"]
    iso = datetime.fromtimestamp(timestamp, tz=UTC).isoformat().replace("+00:00", "Z")
    blockheight = 856_000 + index

    if endpoint["family"] == "institutional_flows":
        return {
            "datetime": iso,
            "blockheight": blockheight,
            "inflow_total": round(value * 10.0, 6),
            "outflow_total": round(value * 11.0, 6),
            "netflow_total": round(value * -1.0, 6),
            "reserve": round(2_450_000.0 + index * 2.0, 6),
            "reserve_usd": round(150_000_000_000.0 + index * 100_000.0, 2),
        }

    if endpoint["family"] == "on_chain_miners":
        return {
            "datetime": iso,
            "blockheight": blockheight,
            "miner_reserve": round(1_800_000.0 + index * 0.2, 6),
            "miner_inflow": round(42.1 + index * 0.01, 6),
            "miner_outflow": round(75.4 + index * 0.01, 6),
            "mpi": round(1.27 + index * 0.001, 6),
            "value": round(value, 6),
        }

    return {"datetime": iso, "blockheight": blockheight, subtype: round(value, 6), "value": round(value, 6)}


def _glassnode_record(endpoint: dict[str, Any], timestamp: int, value: float, index: int) -> dict[str, Any]:
    subtype = endpoint["subtype"]
    if subtype in {"options_open_interest", "options_volume", "exchange_reserve", "stablecoin_flows"}:
        return {
            "t": timestamp,
            "v": {
                "total": round(value, 6),
                "binance": round(value * 0.35, 6),
                "coinbase": round(value * 0.3, 6),
                "okx": round(value * 0.35, 6),
            },
        }
    return {"t": timestamp, "v": round(value, 6)}


def _validate_payload_shape(provider: str, endpoint: dict[str, Any], name: str, payload: Any) -> list[str]:
    errors: list[str] = []
    records: list[Any] = []

    if provider == "coinglass":
        if not isinstance(payload, dict) or payload.get("code") != "0" or payload.get("msg") != "success" or "data" not in payload:
            errors.append(f"{name}: invalid CoinGlass shape")
        records = payload.get("data", []) if isinstance(payload, dict) else []
    elif provider == "cryptoquant":
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), dict) or not isinstance(payload.get("result"), dict):
            errors.append(f"{name}: invalid CryptoQuant shape")
        records = payload.get("result", {}).get("data", []) if isinstance(payload, dict) else []
    elif provider == "glassnode":
        if not isinstance(payload, list):
            errors.append(f"{name}: invalid Glassnode shape")
        records = payload if isinstance(payload, list) else []
    elif provider == "external_indices":
        if not isinstance(payload, dict) or payload.get("index") not in {"bviv", "bvx"} or "data" not in payload:
            errors.append(f"{name}: invalid external index shape")
        records = payload.get("data", []) if isinstance(payload, dict) else []

    if endpoint.get("supports_timeframe") and len(records) < 600:
        errors.append(f"{name}: timeframe file has {len(records)} records < 600")

    if not endpoint.get("supports_timeframe") and name.split("/")[-1].split("_raw.json")[0] in SYNTHETIC_TIMEFRAMES:
        errors.append(f"{name}: non-timeframe data_type uses timeframe")

    return errors


def _expected_members(endpoints: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    members: dict[str, dict[str, Any]] = {}
    for endpoint in endpoints:
        slots = SYNTHETIC_TIMEFRAMES if endpoint.get("supports_timeframe") else tuple(endpoint.get("extraction_windows") or ["latest"])
        for slot in slots:
            members[f"{endpoint['family']}/{endpoint['subtype']}/{slot}_raw.json"] = endpoint
    return members


def _write_zip(root: Path, zip_path: Path) -> None:
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*.json")):
            archive.write(path, path.relative_to(root).as_posix())
    shutil.rmtree(root, ignore_errors=True)


def _load_endpoints(provider: str) -> list[dict[str, Any]]:
    module_name = "endpoint_registry" if provider == "external_indices" else f"endpoint_registry_{provider}"
    module = import_module(f"processing_signals.input.apis.{provider}.{module_name}")
    return list(getattr(module, "ENDPOINTS"))


def _base_value(endpoint: dict[str, Any]) -> float:
    return 50.0 + float(sum(ord(char) for char in endpoint["endpoint_name"]) % 10_000) / 100.0


def _timeframe_seconds(timeframe: str) -> int:
    units = {"m": 60, "h": 3600, "d": 86400}
    try:
        return int(timeframe[:-1]) * units[timeframe[-1]]
    except (KeyError, ValueError, IndexError):
        return 60


def _cryptoquant_window(slot: str) -> str:
    if slot.endswith("m"):
        return "minute"
    if slot.endswith("h"):
        return "hour"
    if slot.endswith("d"):
        return "day"
    return slot


def main() -> None:
    results = generate_all_synthetic_raw_zips()
    print(json.dumps(results, ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()
