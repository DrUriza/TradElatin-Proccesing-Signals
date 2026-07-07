from __future__ import annotations

from typing import Any


class OutputManifestBuilder:
    """Build the Processing manifest after Union has written family outputs."""

    FLOW = [
        "extraction",
        "classification_input",
        "transforms",
        "technical_indicators_on_classified_views",
        "math_statistics_microstructure_patterns",
        "classification_output",
        "union_manifest",
    ]

    def __init__(self, *, pipeline_name: str, version: str, output_path: str) -> None:
        self.pipeline_name = pipeline_name
        self.version = version
        self.output_path = output_path

    def build(
        self,
        blocks: list[dict[str, Any]],
        family_outputs_index: dict[str, Any],
        *,
        write_manifest: bool,
        input_timeframe_issues: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        input_timeframe_issues = list(input_timeframe_issues or [])
        payload = {
            "pipeline": self.pipeline_name,
            "version": self.version,
            "summary": {
                "records_processed": len(blocks),
                "data_types": count_data_types(blocks),
            },
            "records_processed": len(blocks),
            "data_types": count_data_types(blocks),
            "family_outputs": family_outputs_index,
            "official_families": family_outputs_index.get("official_families", []),
            "active_families": family_outputs_index.get("active_families", []),
            "inactive_families": family_outputs_index.get("inactive_families", []),
            "manifest_summary": {"output_shape": "manifest", "records_processed": len(blocks)},
            "processing_flow": self.FLOW,
            "input_timeframe_issues": input_timeframe_issues,
            "validation_status": "warning" if input_timeframe_issues else "ok",
            "errors": [],
            "warnings": [
                f"Requested timeframe {item.get('requested_timeframe')} not available for "
                f"{item.get('provider')}/{item.get('family')}/{item.get('subtype')}"
                for item in input_timeframe_issues
            ],
        }
        if write_manifest:
            payload["manifest_summary"]["path"] = self.output_path
            payload["metaoutputs"] = [
                {
                    "output_shape": "manifest",
                    "path": self.output_path,
                    "records_processed": len(blocks),
                }
            ]
        return payload


def count_data_types(blocks: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for block in blocks:
        classification = block.get("classification_output", {})
        if isinstance(classification, dict) and classification.get("data_type"):
            data_type = str(classification["data_type"])
            counts[data_type] = counts.get(data_type, 0) + 1
            continue
        detected = block.get("detected", {}) if isinstance(block.get("detected"), dict) else {}
        data_type = str(detected.get("data_type") or "unknown")
        counts[data_type] = counts.get(data_type, 0) + 1
    return counts
