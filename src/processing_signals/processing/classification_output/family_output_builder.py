from __future__ import annotations

import json
from pathlib import Path
import shutil
from typing import Any


class FamilyOutputBuilder:
    """Write processed family outputs grouped by Classification Output."""

    def __init__(
        self,
        output_dir: Path,
        *,
        pipeline_name: str,
        version: str,
        max_rows: int,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.pipeline_name = pipeline_name
        self.version = version
        self.max_rows = max_rows

    def write_family_outputs(self, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for block in blocks:
            family = self._family_from_block(block)
            grouped.setdefault(family, []).append(block)

        self._clean_output_dir()
        families: list[dict[str, Any]] = []
        for family_key, family_blocks in sorted(grouped.items()):
            path = self.output_dir / f"{family_key}.json"
            payload = {
                "pipeline": self.pipeline_name,
                "version": self.version,
                "official_family": family_key,
                "records_processed": len(family_blocks),
                "outputs": [self._serialize_block(block) for block in family_blocks],
            }
            with path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, ensure_ascii=False, indent=2, default=to_jsonable)
            families.append(
                {
                    "family_key": family_key,
                    "records_processed": len(family_blocks),
                    "outputs": [{"path": str(path), "records_processed": len(family_blocks)}],
                }
            )

        official_families = sorted(grouped)
        return {
            "root": str(self.output_dir),
            "official_families": official_families,
            "active_families": official_families,
            "inactive_families": [],
            "families": families,
        }

    def _clean_output_dir(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        for child in self.output_dir.iterdir():
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()

    @staticmethod
    def _family_from_block(block: dict[str, Any]) -> str:
        classification = block.get("classification_output", {})
        if isinstance(classification, dict) and classification.get("official_family"):
            return str(classification["official_family"])
        detected = block.get("detected", {})
        metadata = detected.get("metadata", {}) if isinstance(detected, dict) else {}
        if isinstance(metadata, dict):
            return str(metadata.get("official_family") or metadata.get("family") or "unknown")
        return "unknown"

    def _serialize_block(self, block: dict[str, Any]) -> dict[str, Any]:
        normalized = block.get("normalized", {})
        return {
            "source_name": block.get("source_name"),
            "classification_input": block.get("classification_input", {}),
            "classification_output": block.get("classification_output", {}),
            "records_count": normalized.get("records_count") if isinstance(normalized, dict) else None,
            "transforms": preview_payload(block.get("transforms", {}), self.max_rows),
            "math": preview_payload(block.get("math", {}), self.max_rows),
            "view_math": preview_payload(block.get("view_math", {}), self.max_rows),
            "patterns": preview_payload(block.get("patterns", {}), self.max_rows),
        }


def preview_payload(value: Any, max_rows: int) -> Any:
    if hasattr(value, "head") and hasattr(value, "to_dict"):
        return value.head(max_rows).to_dict(orient="records")
    if isinstance(value, dict):
        return {key: preview_payload(item, max_rows) for key, item in value.items()}
    if isinstance(value, list):
        return [preview_payload(item, max_rows) for item in value[:max_rows]]
    return value


def to_jsonable(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return str(value)
