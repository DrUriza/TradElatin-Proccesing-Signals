from __future__ import annotations

from typing import Any, Iterable

from .models import ChartSeriesDescriptor, ProcessingBlock, ValidationIssue
from .target_types import DEFAULT_X_FIELD_CANDIDATES, DEFAULT_Y_FIELD_PREFERRED


def coerce_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Expected a mapping payload")
    return value


def iter_blocks(payload: dict[str, Any]) -> list[ProcessingBlock]:
    blocks = payload.get("blocks")
    if not isinstance(blocks, list):
        return []
    return [item for item in blocks if isinstance(item, dict)]


def extract_rows(block: ProcessingBlock) -> list[dict[str, Any]]:
    data = block.get("data")
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]

    events = block.get("events")
    if isinstance(events, list):
        return [row for row in events if isinstance(row, dict)]

    return []


def resolve_x_field(block: ProcessingBlock, rows: list[dict[str, Any]]) -> str | None:
    timestamp_field = block.get("timestamp_field")
    if isinstance(timestamp_field, str) and rows and timestamp_field in rows[0]:
        return timestamp_field

    for candidate in DEFAULT_X_FIELD_CANDIDATES:
        if rows and candidate in rows[0]:
            return candidate
    return None


def resolve_y_fields(
    block: ProcessingBlock,
    rows: list[dict[str, Any]],
    x_field: str | None,
) -> list[str]:
    if not rows:
        return []

    available_columns = block.get("columns") if isinstance(block.get("columns"), list) else []
    columns: list[str] = [str(column) for column in available_columns]

    preferred: list[str] = []
    for candidate in DEFAULT_Y_FIELD_PREFERRED:
        if candidate == x_field:
            continue
        if candidate in columns or candidate in rows[0]:
            preferred.append(candidate)

    if preferred:
        return preferred

    fallback: list[str] = []
    for key, value in rows[0].items():
        if key == x_field:
            continue
        if isinstance(value, (int, float)):
            fallback.append(key)
    return fallback


def validate_required_fields(
    source_name: str | None,
    output_shape: str,
    row: dict[str, Any],
    required_fields: Iterable[str],
) -> list[ValidationIssue]:
    missing = [field for field in required_fields if field not in row]
    if not missing:
        return []
    return [
        ValidationIssue(
            level="warning",
            message=f"Missing required fields for {output_shape}: {', '.join(missing)}",
            source_name=source_name,
            output_shape=output_shape,
        )
    ]


def build_series_descriptor(
    block: ProcessingBlock,
    output_shape: str,
    required_fields: Iterable[str],
) -> tuple[ChartSeriesDescriptor | None, list[ValidationIssue]]:
    source_name = block.get("source_name") if isinstance(block.get("source_name"), str) else None
    rows = extract_rows(block)
    if not rows:
        return (
            None,
            [
                ValidationIssue(
                    level="warning",
                    message="No chart rows found in block",
                    source_name=source_name,
                    output_shape=output_shape,
                )
            ],
        )

    row0 = rows[0]
    issues = validate_required_fields(source_name, output_shape, row0, required_fields)

    x_field = resolve_x_field(block, rows)
    if x_field is None:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No timestamp/time field available for chart x-axis",
                source_name=source_name,
                output_shape=output_shape,
            )
        )
        return None, issues

    y_fields = resolve_y_fields(block, rows, x_field)
    if not y_fields:
        issues.append(
            ValidationIssue(
                level="warning",
                message="No numeric y fields available for chart",
                source_name=source_name,
                output_shape=output_shape,
            )
        )
        return None, issues

    descriptor = ChartSeriesDescriptor(
        source_name=source_name or "unknown",
        data_type=str(block.get("data_type")) if block.get("data_type") is not None else None,
        symbol=str(block.get("symbol")) if block.get("symbol") is not None else None,
        timeframe=str(block.get("timeframe")) if block.get("timeframe") is not None else None,
        output_shape=output_shape,
        x_field=x_field,
        y_fields=y_fields,
        sample_size=len(rows),
    )
    return descriptor, issues


def sorted_strings(values: list[Any]) -> list[str]:
    return sorted({str(item) for item in values if item is not None})
