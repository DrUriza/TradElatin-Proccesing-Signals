from __future__  import annotations
from dataclasses import dataclass
from pathlib     import Path
from typing      import Any
import argparse
import json
import shutil
import sys
import zipfile

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

PROJECT_ROOT = Path(__file__).resolve().parents[3]

from processing_signals.classification.output_classifier import OutputClassifier
from processing_signals.input.input_pipeline             import run_input_pipeline
from processing_signals.output.family_output_builder     import FamilyOutputBuilder
from processing_signals.output.output_builder            import OutputBuilder
from processing_signals.output.output_family_rules       import resolve_output_family
from processing_signals.output.output_validator          import OutputValidator
from processing_signals.processing.detection.data_type_detector import DataTypeDetector
from processing_signals.processing.indicator_decision_engine    import IndicatorDecisionEngine
from processing_signals.processing.transforms.transform_engine  import TransformEngine
from processing_signals.processing.vectorization.vectorizer     import Vectorizer
from processing_signals.processing.math.math_engine             import ProcessingMathEngine
from processing_signals.processing.normalization.normalizer     import Normalizer
from processing_signals.processing.patterns.pattern_engine      import PatternEngine


def resolve_project_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def ensure_project_directories(
    *,
    input_dir: Path,
    output_path: Path,
    write_manifest: bool = True,
    write_validation_report: bool = True,
) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    (output_path.parent / "families").mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class InputRecord:
    source_name: str
    payload: dict[str, Any]


class NormalizedInputReader:
    """Read normalized Input payloads from a JSON file, ZIP, or directory."""
    def __init__(self, input_path: Path):
        self.input_path = Path(input_path)

    def load(self) -> list[InputRecord]:
        if self.input_path.is_dir():
            return self._load_directory(self.input_path)
        if self.input_path.suffix.lower() == ".zip":
            return self._load_zip(self.input_path)
        return [self._load_file(self.input_path, self.input_path.name)]

    def _load_directory(self, path: Path) -> list[InputRecord]:
        records = [
            self._load_file(json_path, json_path.relative_to(path).as_posix())
            for json_path in sorted(path.rglob("*.json"))
            if json_path.name != "manifest.json"
        ]
        if not records:
            raise FileNotFoundError(f"No normalized JSON payloads found in {path}")
        return records

    def _load_zip(self, path: Path) -> list[InputRecord]:
        records: list[InputRecord] = []
        with zipfile.ZipFile(path, "r") as archive:
            for name in sorted(archive.namelist()):
                if not name.lower().endswith(".json") or Path(name).name == "manifest.json":
                    continue
                payload = json.loads(archive.read(name).decode("utf-8"))
                records.append(InputRecord(source_name=name, payload=_prepare_processing_payload(payload)))
        if not records:
            raise FileNotFoundError(f"No normalized JSON payloads found in {path}")
        return records

    def _load_file(self, path: Path, source_name: str) -> InputRecord:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return InputRecord(source_name=source_name, payload=_prepare_processing_payload(payload))


def _prepare_processing_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
    if input_data_type in {"time_series", "snapshot", "event_list", "heatmap"} and subtype:
        if input_data_type == "time_series" and subtype == "orderbook_conventional":
            metadata["data_type"] = "market_depth"
        else:
            metadata["data_type"] = subtype
    item["metadata"] = metadata
    return item


def promote_input_manifest(normalized_dir: Path) -> Path | None:
    source = normalized_dir / "manifest.json"
    if not source.exists():
        return None

    target = normalized_dir.parent / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    source.unlink()
    return target


class MainPipeline:
    """Orchestrates input, processing, math, patterns, classification, and output."""

    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        max_rows: int | None = None,
        write_validation_report: bool = False,
        write_manifest: bool = False,
    ):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.write_validation_report = write_validation_report
        self.write_manifest = write_manifest
        self.loader = NormalizedInputReader(self.input_path)
        self.detector = DataTypeDetector()
        self.normalizer = Normalizer()
        self.vectorizer = Vectorizer()
        self.transform_engine = TransformEngine()
        self.decision_engine = IndicatorDecisionEngine()
        self.math_engine = ProcessingMathEngine()
        self.pattern_engine = PatternEngine()
        self.classifier = OutputClassifier()
        self.output_builder = OutputBuilder(max_rows=max_rows)

    def run(self) -> dict[str, Any]:
        raw_payloads = self.loader.load()
        detected_blocks = self._detect_blocks(raw_payloads)
        normalized_blocks = self._normalize_blocks(detected_blocks)
        vectorized_blocks = self._vectorize_blocks(normalized_blocks)
        transformed_blocks = self._transform_blocks(vectorized_blocks)
        math_blocks = self._run_math(transformed_blocks)
        pattern_blocks = self._run_patterns(math_blocks)
        blocks = self._classify_blocks(pattern_blocks)
        family_output_dir = self.output_path.parent / "families"

        for block in blocks:
            family_info = resolve_output_family(block)
            block.update(family_info)
            if family_info.get("is_metadata"):
                block["family_output_path"] = str(self.output_path) if self.write_manifest else ""
            else:
                block["family_output_path"] = str(
                    family_output_dir / family_info["family_key"] / family_info["output_filename"]
                )

        family_builder = FamilyOutputBuilder(
            output_dir=family_output_dir,
            pipeline_name="Processing-Signals MainPipeline",
            version="0.1.0",
        )
        family_outputs_index         = family_builder.write_family_outputs(blocks)
        payload                      = self.output_builder.build(blocks)
        payload["family_outputs"]    = family_outputs_index
        payload["official_families"] = family_outputs_index.get("official_families", [])
        payload["active_families"]   = family_outputs_index.get("active_families", [])
        payload["inactive_families"] = family_outputs_index.get("inactive_families", [])
        manifest = self.output_builder.build_manifest(blocks)
        validation_report = OutputValidator(self.output_path.parent).validate()
        payload["manifest_summary"]  = {"output_shape": manifest["output_shape"], "records_processed": manifest["records_processed"]}
        payload["validation"]        = validation_report
        payload["validation_status"] = validation_report["status"]
        payload["errors"]            = validation_report.get("errors", [])
        payload["warnings"]          = [*payload.get("warnings", []), *validation_report.get("warnings", [])]

        if self.write_manifest:
            payload["manifest_summary"]["path"] = str(self.output_path)
            payload["metaoutputs"] = [{"output_shape": "manifest",
                                       "path": str(self.output_path),
                                       "records_processed": manifest["records_processed"]}]
        self.output_builder.write_json(payload, self.output_path)
        return payload

    def _detect_blocks(self, raw_payloads: list[InputRecord]) -> list[dict[str, Any]]:
        return [{"source_name": record.source_name,
                 "raw_payload": record.payload,
                 "detected": self.detector.detect(record.payload, source_name=record.source_name)} for record in raw_payloads]

    def _normalize_blocks(self, detected_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in detected_blocks:
            block["normalized"] = self.normalizer.normalize(block["raw_payload"], block["detected"])
        return detected_blocks

    def _vectorize_blocks(self, normalized_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in normalized_blocks:
            block["vectorized"] = self.vectorizer.vectorize(block["normalized"], block["detected"])
        return normalized_blocks

    def _transform_blocks(self, vectorized_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in vectorized_blocks:
            block["transforms"] = self.transform_engine.transform(
                block["normalized"],
                block["detected"],
                block["vectorized"],
            )
        return vectorized_blocks

    def _run_math(self, transformed_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in transformed_blocks:
            decision = self.decision_engine.decide(block["detected"], block["normalized"])
            block["decision"] = decision
            block["math"] = self.math_engine.compute(block["normalized"], decision)
            block["view_math"] = self.math_engine.compute_view_math(block["transforms"])
        return transformed_blocks

    def _run_patterns(self, math_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in math_blocks:
            block["patterns"] = self.pattern_engine.detect(
                block["normalized"],
                block["math"],
                block["decision"],
                transforms=block.get("transforms", {}),
                view_math=block.get("view_math", {}),
            )
        return math_blocks

    def _classify_blocks(self, pattern_blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for block in pattern_blocks:
            block["routes"] = self.classifier.classify(
                block["detected"],
                block["normalized"],
                block["math"],
                block["patterns"],
                block["decision"],
            )
            block.pop("raw_payload", None)
        return pattern_blocks

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Processing-Signals main pipeline: input -> processing -> math -> classification -> output.")
    parser.add_argument("--input", default=None,
                        help="Input JSON file, ZIP file, or directory containing normalized JSON files. Defaults to data_input/families.")
    parser.add_argument("--generate-input", choices=["synthetic"], default="synthetic",
                        help="Generate normalized Input payloads before Processing. Defaults to synthetic.")
    parser.add_argument("--no-generate-input", action="store_true",
                        help="Do not generate Input synthetic data; use existing data_input/families or --input.")
    parser.add_argument("--output", default="data_output/manifest.json",
                        help="Output JSON path.")
    parser.add_argument("--max-rows", type=int, default=20, 
                        help="Optional row limit for small previews in the master report.")
    parser.add_argument("--write-validation-report", action=argparse.BooleanOptionalAction, default=False, 
                        help="Deprecated no-op. Validation is embedded in data_output/manifest.json.")
    parser.add_argument("--write-manifest", action=argparse.BooleanOptionalAction, default=True, 
                        help="Write data_output/manifest.json. Enabled by default.")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    output_path = resolve_project_path(args.output)
    default_input_path = resolve_project_path("data_input/families")

    if args.input:
        input_path = resolve_project_path(args.input)
    else:
        input_path = default_input_path

    ensure_project_directories(
        input_dir=input_path if input_path.suffix == "" else input_path.parent,
        output_path=output_path,
        write_manifest=args.write_manifest,
        write_validation_report=args.write_validation_report,
    )

    should_generate_input = (
        not args.no_generate_input
        and args.generate_input == "synthetic"
        and args.input is None
    )

    if should_generate_input:
        input_result = run_input_pipeline(
            mode="synthetic",
            providers=["coinglass", "cryptoquant", "glassnode", "external_indices"],
            asset="BTC",
            symbol="BTCUSDT",
            output_dir=default_input_path,
            min_records=600,
        )
        if input_result.get("status") not in {"ok", "warning"}:
            raise RuntimeError(f"Input generation failed: {input_result}")
        input_path = Path(input_result["output_path"])
        promote_input_manifest(input_path)
    elif args.input is None:
        input_path = resolve_input_path(None)

    if input_path.is_dir() and input_path.name in {"families", "normalized"}:
        promote_input_manifest(input_path)

    pipeline = MainPipeline(
        input_path=input_path,
        output_path=output_path,
        max_rows=args.max_rows,
        write_validation_report=args.write_validation_report,
        write_manifest=args.write_manifest,
    )
    result = pipeline.run()
    print("input:")
    print(input_path.resolve())
    print()
    print(f"records_processed: {result['summary']['records_processed']}")
    print()
    print("data_types:")
    for data_type, count in result["summary"]["data_types"].items():
        print(f"{data_type}: {count}")
    print()
    print("main_output:")
    print(output_path.resolve())
    print()
    print(f"validation_status: {result.get('validation_status')}")
    print()
    if args.write_manifest:
        print("manifest:")
        for output in result.get("metaoutputs", []):
            print(output["path"])
        print()
    print("official_families:")
    for family_key in result.get("family_outputs", {}).get("official_families", []):
        print(family_key)
    print()
    print("active_families:")
    for family_key in result.get("family_outputs", {}).get("active_families", []):
        print(family_key)
    print()
    print("inactive_families:")
    for family_key in result.get("family_outputs", {}).get("inactive_families", []):
        print(family_key)
    print()
    print("family_outputs:")
    for family in result.get("family_outputs", {}).get("families", []):
        print(f"{family['family_key']}:")
        for output in family.get("outputs", []):
            print(output["path"])
        print()


def resolve_input_path(input_arg: str | None) -> Path:
    if input_arg:
        return resolve_project_path(input_arg)

    families_dir = resolve_project_path("data_input/families")
    if families_dir.exists():
        return families_dir

    normalized_dir = resolve_project_path("data_input/normalized")
    if normalized_dir.exists():
        return normalized_dir

    input_dir = resolve_project_path("data_input")
    input_dir.mkdir(parents=True, exist_ok=True)

    candidates = [
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".zip", ".json"}
    ]
    candidates.sort(key=lambda path: (path.suffix.lower() != ".zip", path.name.lower()))

    if not candidates:
        raise FileNotFoundError(
            "No normalized input found. Run with default synthetic generation or provide --input."
        )

    return candidates[0]


if __name__ == "__main__":
    main()
