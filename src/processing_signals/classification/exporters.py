from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .models import FamilyChartPayload, FamilyProcessingPayload, ValidationIssue
from .routing_rules import RoutingRule
from .validators import build_series_descriptor, iter_blocks, sorted_strings


def build_family_chart_payload(
    *,
    rule: RoutingRule,
    family_payload_by_shape: dict[str, FamilyProcessingPayload],
) -> FamilyChartPayload:
    issues: list[ValidationIssue] = []

    selected_shape: str | None = None
    selected_payload: FamilyProcessingPayload | None = None
    for shape in rule.preferred_output_shapes:
        payload = family_payload_by_shape.get(shape)
        if payload is not None:
            selected_shape = shape
            selected_payload = payload
            break

    if selected_payload is None and family_payload_by_shape:
        selected_shape, selected_payload = next(iter(family_payload_by_shape.items()))

    if selected_payload is None:
        return FamilyChartPayload(
            family_key=rule.family_key,
            module_key=rule.module_key,
            hmi_window_mode=rule.hmi_window_mode,
            selected_output_shape=None,
            status="empty",
            records_processed=0,
            symbols=[],
            timeframes=[],
            series=[],
            issues=[ValidationIssue(level="warning", message="No family payloads found")],
        )

    required_fields = rule.required_fields_by_shape.get(selected_shape or "", tuple())
    series = []
    symbols: list[Any] = []
    timeframes: list[Any] = []
    records_processed = int(selected_payload.get("records_processed", 0) or 0)

    for block in iter_blocks(selected_payload):
        descriptor, block_issues = build_series_descriptor(block, selected_shape or "unknown", required_fields)
        issues.extend(block_issues)
        if descriptor is not None:
            series.append(descriptor)
            symbols.append(descriptor.symbol)
            timeframes.append(descriptor.timeframe)

    if not series:
        status = "warning"
        issues.append(
            ValidationIssue(
                level="warning",
                message="No chart-ready series could be created from selected family payload",
                output_shape=selected_shape,
            )
        )
    else:
        status = "ok"

    return FamilyChartPayload(
        family_key=rule.family_key,
        module_key=rule.module_key,
        hmi_window_mode=rule.hmi_window_mode,
        selected_output_shape=selected_shape,
        status=status,
        records_processed=records_processed,
        symbols=sorted_strings(symbols),
        timeframes=sorted_strings(timeframes),
        series=series,
        issues=issues,
    )


def build_classification_output(
    *,
    input_path: Path,
    output_dir: Path,
    family_results: list[FamilyChartPayload],
    source_file_count: int,
    warnings: list[str],
) -> dict[str, Any]:
    family_status_counts: dict[str, int] = {}
    for result in family_results:
        family_status_counts[result.status] = family_status_counts.get(result.status, 0) + 1

    return {
        "pipeline": "Processing-Signals ClassificationPipeline",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "source_files": source_file_count,
        "summary": {
            "families_processed": len(family_results),
            "status_counts": family_status_counts,
        },
        "warnings": warnings,
        "families": [result.to_dict() for result in family_results],
    }


def build_hmi_manifest(
    *,
    input_path: Path,
    output_dir: Path,
    family_results: list[FamilyChartPayload],
    family_payload_paths: dict[str, Path],
) -> dict[str, Any]:
    return {
        "pipeline": "Processing-Signals ClassificationPipeline",
        "version": "0.1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "output_dir": str(output_dir),
        "families": [
            {
                "family_key": result.family_key,
                "module_key": result.module_key,
                "hmi_window_mode": result.hmi_window_mode,
                "selected_output_shape": result.selected_output_shape,
                "status": result.status,
                "chart_payload_path": str(family_payload_paths[result.family_key]),
                "series_count": len(result.series),
            }
            for result in family_results
        ],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def export_all_outputs(
    *,
    output_dir: Path,
    classification_output: dict[str, Any],
    hmi_manifest: dict[str, Any],
    family_results: list[FamilyChartPayload],
) -> dict[str, str]:
    family_dir = output_dir / "families"
    family_payload_paths: dict[str, Path] = {}
    for family_result in family_results:
        payload_path = family_dir / f"{family_result.family_key}_chart_payload.json"
        write_json(payload_path, family_result.to_dict())
        family_payload_paths[family_result.family_key] = payload_path

    classification_path = output_dir / "classification_output.json"
    hmi_path = output_dir / "hmi_manifest.json"
    write_json(classification_path, classification_output)
    write_json(hmi_path, hmi_manifest)

    return {
        "classification_output": str(classification_path),
        "hmi_manifest": str(hmi_path),
        "families_dir": str(family_dir),
    }
