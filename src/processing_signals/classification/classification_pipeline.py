from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .cvd_volume_orderflow.cvd_volume_orderflow import classify as classify_cvd_volume_orderflow
from .exporters import (
    build_classification_output,
    build_hmi_manifest,
    export_all_outputs,
)
from .institutional_flows.institutional_flows import classify as classify_institutional_flows
from .liquidations.liquidations import classify as classify_liquidations
from .liquidity_microstructure.liquidity_microstructure import classify as classify_liquidity_microstructure
from .models import FamilyChartPayload, FamilyProcessingPayload
from .onchain_miners.onchain_miners import classify as classify_onchain_miners
from .open_interest_and_funding.open_interest_and_funding import classify as classify_open_interest_and_funding
from .options_volatility.options_volatility import classify as classify_options_volatility
from .prices_ohlcv.prices_ohlcv import classify as classify_prices_ohlcv
from .routing_rules import canonical_family_key, get_rule_for_family
from .sentiment_positioning.sentiment_positioning import classify as classify_sentiment_positioning
from .validators import coerce_mapping


FamilyClassifier = Callable[[dict[str, FamilyProcessingPayload]], FamilyChartPayload]


FAMILY_CLASSIFIERS: dict[str, FamilyClassifier] = {
    "prices_ohlcv": classify_prices_ohlcv,
    "liquidity_microstructure": classify_liquidity_microstructure,
    "cvd_volume_orderflow": classify_cvd_volume_orderflow,
    "institutional_flows": classify_institutional_flows,
    "liquidations": classify_liquidations,
    "open_interest_and_funding": classify_open_interest_and_funding,
    "sentiment_positioning": classify_sentiment_positioning,
    "onchain_miners": classify_onchain_miners,
    "options_volatility": classify_options_volatility,
}


class ClassificationPipeline:
    def __init__(self, input_path: Path, output_dir: Path):
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)

    def run(self) -> dict:
        processing_payload = self.load_processing_data()
        classification_payload = self.classify_all_families(processing_payload)
        self.export_outputs(classification_payload)
        return classification_payload

    def load_processing_data(self) -> dict:
        if not self.input_path.exists():
            raise FileNotFoundError(f"Processing input path does not exist: {self.input_path}")

        files = self._discover_processing_files(self.input_path)
        families: dict[str, dict[str, FamilyProcessingPayload]] = {}
        warnings: list[str] = []

        for file_path in files:
            try:
                payload = coerce_mapping(json.loads(file_path.read_text(encoding="utf-8")))
            except (ValueError, json.JSONDecodeError) as exc:
                warnings.append(f"Skipping invalid JSON payload at {file_path}: {exc}")
                continue

            family_key_raw = payload.get("family_key") or payload.get("family")
            if not isinstance(family_key_raw, str) or not family_key_raw.strip():
                warnings.append(f"Skipping payload without family_key: {file_path}")
                continue

            output_shape_raw = payload.get("output_shape")
            output_shape = str(output_shape_raw).strip() if output_shape_raw else file_path.stem
            canonical_key = canonical_family_key(family_key_raw)

            family_payloads = families.setdefault(canonical_key, {})
            family_payloads[output_shape] = payload

        return {
            "families": families,
            "source_files": [str(path) for path in files],
            "warnings": warnings,
        }

    def classify_all_families(self, processing_payload: dict) -> dict:
        families = processing_payload.get("families")
        if not isinstance(families, dict):
            raise ValueError("Invalid processing payload: missing families map")

        warnings = list(processing_payload.get("warnings", []))
        results: list[FamilyChartPayload] = []

        for family_key in sorted(families.keys()):
            payload_by_shape = families[family_key]
            if not isinstance(payload_by_shape, dict):
                warnings.append(f"Skipping malformed family payload map: {family_key}")
                continue

            rule = get_rule_for_family(family_key)
            if rule is None:
                warnings.append(f"No routing rule configured for family {family_key}")
                continue

            classifier = FAMILY_CLASSIFIERS.get(rule.module_key)
            if classifier is None:
                warnings.append(
                    f"No classifier module mapped for family {family_key} (module_key={rule.module_key})"
                )
                continue

            typed_payload_by_shape: dict[str, FamilyProcessingPayload] = {}
            for shape_key, payload in payload_by_shape.items():
                if isinstance(shape_key, str) and isinstance(payload, dict):
                    typed_payload_by_shape[shape_key] = payload

            results.append(classifier(typed_payload_by_shape))

        return {
            "family_results": results,
            "source_files": processing_payload.get("source_files", []),
            "warnings": warnings,
        }

    def export_outputs(self, classification_payload: dict) -> None:
        family_results = classification_payload.get("family_results")
        if not isinstance(family_results, list):
            raise ValueError("Invalid classification payload: missing family_results")

        typed_results = [item for item in family_results if isinstance(item, FamilyChartPayload)]
        source_files = classification_payload.get("source_files")
        source_file_count = len(source_files) if isinstance(source_files, list) else 0
        warnings = classification_payload.get("warnings")
        warning_list = [str(item) for item in warnings] if isinstance(warnings, list) else []

        classification_output = build_classification_output(
            input_path=self.input_path,
            output_dir=self.output_dir,
            family_results=typed_results,
            source_file_count=source_file_count,
            warnings=warning_list,
        )

        family_payload_paths = {
            result.family_key: self.output_dir / "families" / f"{result.family_key}_chart_payload.json"
            for result in typed_results
        }

        hmi_manifest = build_hmi_manifest(
            input_path=self.input_path,
            output_dir=self.output_dir,
            family_results=typed_results,
            family_payload_paths=family_payload_paths,
        )

        output_paths = export_all_outputs(
            output_dir=self.output_dir,
            classification_output=classification_output,
            hmi_manifest=hmi_manifest,
            family_results=typed_results,
        )

        classification_payload["classification_output"] = classification_output
        classification_payload["hmi_manifest"] = hmi_manifest
        classification_payload["output_paths"] = output_paths

    def _discover_processing_files(self, input_path: Path) -> list[Path]:
        if input_path.is_file():
            if input_path.suffix.lower() != ".json":
                raise ValueError(f"Input file must be JSON: {input_path}")
            return [input_path]

        manifest_paths = self._discover_files_from_manifest(input_path)
        if manifest_paths:
            return manifest_paths

        files = [
            path
            for path in sorted(input_path.rglob("*.json"))
            if path.name not in {"manifest.json", "classification_output.json", "hmi_manifest.json"}
        ]
        if not files:
            raise FileNotFoundError(f"No processing JSON payloads found under {input_path}")
        return files

    def _discover_files_from_manifest(self, input_dir: Path) -> list[Path]:
        manifest_path = input_dir / "manifest.json"
        if not manifest_path.exists():
            return []

        try:
            manifest = coerce_mapping(json.loads(manifest_path.read_text(encoding="utf-8")))
        except (ValueError, json.JSONDecodeError):
            return []

        family_outputs = manifest.get("family_outputs")
        if not isinstance(family_outputs, dict):
            return []

        families = family_outputs.get("families")
        if not isinstance(families, list):
            return []

        discovered: list[Path] = []
        for family_item in families:
            if not isinstance(family_item, dict):
                continue
            outputs = family_item.get("outputs")
            if not isinstance(outputs, list):
                continue
            for output_item in outputs:
                if not isinstance(output_item, dict):
                    continue
                raw_path = output_item.get("path")
                if not isinstance(raw_path, str) or not raw_path.strip():
                    continue
                path = Path(raw_path)
                if not path.is_absolute():
                    path = (manifest_path.parent / path).resolve()
                if path.exists() and path.suffix.lower() == ".json":
                    discovered.append(path)

        unique = sorted({path for path in discovered})
        return unique


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Processing-Signals classification pipeline for HMI routing and chart payload generation."
    )
    parser.add_argument(
        "--input",
        default="data/data_processing",
        help="Processing output directory or JSON file. Defaults to data/data_processing.",
    )
    parser.add_argument(
        "--output",
        default="data/classification_data",
        help="Output directory for classification manifests and family chart payloads.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pipeline = ClassificationPipeline(input_path=Path(args.input), output_dir=Path(args.output))
    result = pipeline.run()

    output_paths = result.get("output_paths", {})
    summary = result.get("classification_output", {}).get("summary", {})

    print("classification_pipeline: Processing-Signals ClassificationPipeline")
    print(f"input_path: {Path(args.input).resolve()}")
    print(f"output_dir: {Path(args.output).resolve()}")
    print(f"families_processed: {summary.get('families_processed', 0)}")
    print(f"status_counts: {summary.get('status_counts', {})}")
    print(f"classification_output: {output_paths.get('classification_output')}")
    print(f"hmi_manifest: {output_paths.get('hmi_manifest')}")


if __name__ == "__main__":
    main()
