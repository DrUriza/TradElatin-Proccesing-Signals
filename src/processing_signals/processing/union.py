from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from processing_signals.processing.classification_output.family_output_builder import FamilyOutputBuilder
from processing_signals.processing.classification_output.output_manifest_builder import OutputManifestBuilder


class ProcessingUnion:
    """Union Classification Output blocks into family outputs and a manifest."""

    def __init__(
        self,
        output_path: Path,
        *,
        max_rows: int = 500,
        pipeline_name: str = "Processing-Signals ProcessingPipeline",
        version: str = "0.1.0",
    ) -> None:
        self.output_path = Path(output_path)
        self.max_rows = max_rows
        self.pipeline_name = pipeline_name
        self.version = version

    def union(
        self,
        blocks: list[dict[str, Any]],
        *,
        write_manifest: bool = False,
        input_timeframe_issues: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        family_builder = FamilyOutputBuilder(
            output_dir=self.output_path.parent / "families",
            pipeline_name=self.pipeline_name,
            version=self.version,
            max_rows=self.max_rows,
        )
        family_outputs_index = family_builder.write_family_outputs(blocks)
        manifest_builder = OutputManifestBuilder(
            pipeline_name=self.pipeline_name,
            version=self.version,
            output_path=str(self.output_path),
        )
        payload = manifest_builder.build(
            blocks,
            family_outputs_index,
            write_manifest=write_manifest,
            input_timeframe_issues=input_timeframe_issues,
        )

        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        with self.output_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
        return payload
