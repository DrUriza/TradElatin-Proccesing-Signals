"""Normalize extracted raw Input files from disk."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any


def normalize_extracted_raw(provider: str, run_id: str) -> list[dict[str, Any]]:
    """Normalize raw files previously written under a provider extracted_raw run."""
    root = Path(__file__).resolve().parent / "apis" / provider / "extracted_raw" / run_id
    if not root.exists():
        return []

    normalized: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/*/*_raw.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("status") != "ok":
            continue

        records = _extract_records(raw)
        records = [normalize_timestamp_field(record) for record in records]
        before_dedup = len(records)
        records = ensure_unix_seconds(records)
        records = cast_numeric_strings(records)
        records = drop_duplicate_timestamps(records)
        duplicates_removed = before_dedup - len(records)
        records = sort_by_timestamp(records)

        min_required = int(raw.get("metadata", {}).get("min_records", 0) or 0)
        if raw.get("data_type") in {"snapshot", "event_list", "heatmap", "matrix"}:
            min_required = 0

        normalized.append(
            {
                "schema_version": "1.0",
                "run_id": run_id,
                "provider": raw["provider"],
                "family": raw["family"],
                "subtype": raw["subtype"],
                "data_type": raw["data_type"],
                "asset": raw["asset"],
                "symbol": raw["symbol"],
                "exchange": raw.get("exchange"),
                "timeframe": raw.get("timeframe"),
                "extraction_window": raw.get("extraction_window"),
                "records": records,
                "metadata": {
                    "source": "synthetic" if raw.get("mode") == "synthetic" else "api",
                    "provider_endpoint": raw["endpoint_name"],
                    "path": raw.get("metadata", {}).get("path"),
                    "raw_file": path.as_posix(),
                    "raw_shape": raw.get("metadata", {}).get("raw_shape"),
                    "loader_strategy": raw.get("metadata", {}).get("loader_strategy"),
                    "row_timestamp_required": raw.get("metadata", {}).get("row_timestamp_required"),
                },
                "quality": evaluate_quality(records, min_required, duplicates_removed),
            }
        )
    return normalized


def normalize_timestamp_field(record: dict[str, Any]) -> dict[str, Any]:
    item = dict(record)

    value = (
        item.get("timestamp")
        or item.get("time")
        or item.get("t")
        or item.get("datetime")
        or item.get("date")
    )

    if value is None:
        return item

    if isinstance(value, (int, float)):
        timestamp = int(value)
        if timestamp > 10_000_000_000:
            timestamp = timestamp // 1000
        item["timestamp"] = timestamp
        return item

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            item["timestamp"] = int(parsed.timestamp())
            return item
        except ValueError:
            return item

    return item


def ensure_unix_seconds(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        item = dict(record)
        timestamp = item.get("timestamp")
        if isinstance(timestamp, (int, float)) and timestamp > 10_000_000_000:
            item["timestamp"] = int(timestamp // 1000)
        output.append(item)
    return output


def cast_numeric_strings(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for record in records:
        item: dict[str, Any] = {}
        for key, value in record.items():
            if isinstance(value, str):
                try:
                    item[key] = float(value)
                    continue
                except ValueError:
                    pass
            item[key] = value
        output.append(item)
    return output


def drop_duplicate_timestamps(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[Any] = set()
    output: list[dict[str, Any]] = []
    for record in records:
        timestamp = record.get("timestamp")
        if timestamp is None:
            output.append(record)
            continue

        if timestamp in seen:
            continue

        seen.add(timestamp)
        output.append(record)
    return output


def sort_by_timestamp(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(records, key=lambda item: item.get("timestamp", 0))


def evaluate_quality(records: list[dict[str, Any]], min_required: int, duplicates_removed: int) -> dict[str, Any]:
    status = "ok" if len(records) >= min_required else "warning"
    return {
        "status": status,
        "records_count": len(records),
        "min_records_required": min_required,
        "duplicates_removed": duplicates_removed,
    }


def _extract_records(raw: dict[str, Any]) -> list[dict[str, Any]]:
    provider = raw.get("provider")
    response = raw.get("raw_response")

    if provider == "coinglass" and isinstance(response, dict):
        return _records_from_items(response.get("data", []))

    if provider == "cryptoquant" and isinstance(response, dict):
        result = response.get("result", {})
        if isinstance(result, dict):
            return _records_from_items(result.get("data", []))
        return []

    if provider == "glassnode" and isinstance(response, list):
        return [
            {"timestamp": item.get("t"), "value": item.get("v")}
            for item in response
            if isinstance(item, dict)
        ]

    if provider in {"volmex", "cme_cf_benchmarks"} and isinstance(response, dict):
        return _records_from_items(response.get("data", []))

    if isinstance(response, dict):
        return _records_from_items(response.get("data", []))
    if isinstance(response, list):
        return _records_from_items(response)
    return []


def _records_from_items(items: Any) -> list[dict[str, Any]]:
    if isinstance(items, dict):
        return [dict(items)]
    if not isinstance(items, list):
        return []
    return [dict(item) for item in items if isinstance(item, dict)]
