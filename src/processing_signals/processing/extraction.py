from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any
import zipfile


@dataclass(frozen=True)
class ProcessingInputRecord:
    source_name: str
    payload: dict[str, Any]


class ProcessingExtraction:
    """Extract normalized Input payloads for the Processing stage."""

    def __init__(self, input_path: Path):
        self.input_path = Path(input_path)

    def extract(self) -> list[ProcessingInputRecord]:
        if self.input_path.is_dir():
            return self._extract_directory(self.input_path)
        if self.input_path.suffix.lower() == ".zip":
            return self._extract_zip(self.input_path)
        if is_manifest_name(self.input_path.name):
            raise FileNotFoundError(f"Processing input file is a manifest, not a data block: {self.input_path}")
        return [self._extract_file(self.input_path, self.input_path.name)]

    def _extract_directory(self, path: Path) -> list[ProcessingInputRecord]:
        records: list[ProcessingInputRecord] = []
        for json_path in sorted(path.rglob("*.json")):
            source_name = normalize_source_name(json_path.relative_to(path).as_posix())
            if is_manifest_name(source_name):
                continue
            record = self._extract_file(json_path, source_name)
            records.append(record)
        if not records:
            raise FileNotFoundError(f"No normalized JSON payloads found in {path}")
        return records

    def _extract_zip(self, path: Path) -> list[ProcessingInputRecord]:
        records: list[ProcessingInputRecord] = []
        with zipfile.ZipFile(path, "r") as archive:
            for name in sorted(archive.namelist()):
                source_name = normalize_source_name(name)
                if not source_name.lower().endswith(".json") or is_manifest_name(source_name):
                    continue
                payload = prepare_processing_payload(json.loads(archive.read(name).decode("utf-8")))
                records.append(ProcessingInputRecord(source_name=source_name, payload=payload))
        if not records:
            raise FileNotFoundError(f"No normalized JSON payloads found in {path}")
        return records

    def _extract_file(self, path: Path, source_name: str) -> ProcessingInputRecord:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ProcessingInputRecord(source_name=normalize_source_name(source_name), payload=prepare_processing_payload(payload))


def normalize_source_name(source_name: str) -> str:
    return str(source_name).replace("\\", "/")


def is_manifest_name(source_name: str) -> bool:
    normalized = normalize_source_name(source_name).lower().strip("/")
    return normalized == "manifest.json" or normalized.endswith("/manifest.json")


def prepare_processing_payload(payload: dict[str, Any]) -> dict[str, Any]:
    item = dict(payload)
    metadata = dict(item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {})
    for key in [
        "provider",
        "family",
        "subtype",
        "data_type",
        "asset",
        "symbol",
        "exchange",
        "timeframe",
        "extraction_window",
        "run_id",
    ]:
        if key in item and key not in metadata:
            metadata[key] = item[key]
    if "family" in item and "family_key" not in metadata:
        metadata["family_key"] = item["family"]
    input_data_type = str(item.get("data_type") or metadata.get("data_type") or "")
    subtype = str(item.get("subtype") or metadata.get("subtype") or "")
    if input_data_type:
        metadata["input_data_type"] = input_data_type
        metadata["structural_data_type"] = input_data_type
    if subtype:
        metadata["semantic_subtype"] = subtype
    item["metadata"] = metadata
    return item
