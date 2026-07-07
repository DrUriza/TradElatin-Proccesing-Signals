from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from processing_signals.input.input_pipeline import DEFAULT_PROVIDERS, run_input_pipeline
from processing_signals.processing.processing_pipeline import ProcessingPipeline


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def resolve_project_path(path: str | Path) -> Path:
    path = Path(path)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def ensure_project_directories(*, input_dir: Path, output_path: Path) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    output_path.parent.mkdir(parents=True, exist_ok=True)


def promote_input_manifest(normalized_dir: Path) -> Path | None:
    source = normalized_dir / "manifest.json"
    if not source.exists():
        return None

    target = normalized_dir.parent / "manifest.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    source.unlink()
    return target


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Processing-Signals pipeline: optional input generation -> processing -> output."
    )
    parser.add_argument(
        "--input",
        default=None,
        help="Input JSON file, ZIP file, or directory containing normalized JSON files. Defaults to data/data_input/families.",
    )
    parser.add_argument(
        "--generate-input",
        choices=["synthetic"],
        default="synthetic",
        help="Generate normalized Input payloads before Processing. Defaults to synthetic.",
    )
    parser.add_argument(
        "--no-generate-input",
        action="store_true",
        help="Do not generate Input synthetic data; use existing data/data_input/families or --input.",
    )
    parser.add_argument(
        "--output",
        default="data/data_processing/manifest.json",
        help="Output JSON path.",
    )
    parser.add_argument(
        "--max-rows",
        type=int,
        default=20,
        help="Optional row limit for small previews in the master report.",
    )
    parser.add_argument(
        "--write-validation-report",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Deprecated no-op. Validation is embedded in data/data_processing/manifest.json.",
    )
    parser.add_argument(
        "--write-manifest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write data/data_processing/manifest.json. Enabled by default.",
    )
    parser.add_argument("--verbose-output", action="store_true", help="Print every family output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_path = resolve_project_path(args.output)
    default_input_path = resolve_project_path("data/data_input/families")
    input_timeframe_issues: list[dict[str, object]] = []

    input_path = resolve_project_path(args.input) if args.input else default_input_path

    ensure_project_directories(
        input_dir=input_path if input_path.suffix == "" else input_path.parent,
        output_path=output_path,
    )

    should_generate_input = (
        not args.no_generate_input
        and args.generate_input == "synthetic"
        and args.input is None
    )

    if should_generate_input:
        input_result = run_input_pipeline(
            mode="synthetic",
            providers=list(DEFAULT_PROVIDERS),
            asset="BTC",
            symbol="BTCUSDT",
            output_dir=default_input_path,
            min_records=600,
        )
        if input_result.get("status") not in {"ok", "warning"}:
            raise RuntimeError(f"Input generation failed: {input_result}")
        input_timeframe_issues = list(input_result.get("unavailable_timeframes", []))
        input_path = Path(input_result["output_path"])
        promote_input_manifest(input_path)
    elif args.input is None:
        input_path = resolve_input_path(None)

    input_timeframe_issues = input_timeframe_issues or read_input_timeframe_issues(input_path)
    if input_path.is_dir() and input_path.name in {"families", "normalized"}:
        promote_input_manifest(input_path)

    pipeline = ProcessingPipeline(
        input_path=input_path,
        output_path=output_path,
        max_rows=args.max_rows,
        write_validation_report=args.write_validation_report,
        write_manifest=args.write_manifest,
        input_timeframe_issues=input_timeframe_issues,
    )
    result = pipeline.run()
    print_processing_summary(
        input_path=input_path,
        output_path=output_path,
        result=result,
        write_manifest=args.write_manifest,
        verbose_output=args.verbose_output,
    )


def read_input_timeframe_issues(input_path: Path) -> list[dict[str, object]]:
    input_manifest_path = input_path.parent / "manifest.json"
    if not input_manifest_path.exists():
        return []

    try:
        input_manifest = json.loads(input_manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return list(input_manifest.get("unavailable_timeframes", []))


def print_processing_summary(
    *,
    input_path: Path,
    output_path: Path,
    result: dict[str, object],
    write_manifest: bool,
    verbose_output: bool,
) -> None:
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
    if write_manifest:
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
    family_outputs = result.get("family_outputs", {}).get("families", [])
    output_count = sum(len(family.get("outputs", [])) for family in family_outputs)
    print("family_outputs:")
    print(f"families: {len(family_outputs)}")
    print(f"files: {output_count}")
    print(f"root: {output_path.parent / 'families'}")
    if verbose_output:
        print()
        for family in family_outputs:
            print(f"{family['family_key']}:")
            for output in family.get("outputs", []):
                print(output["path"])
            print()


def resolve_input_path(input_arg: str | None) -> Path:
    if input_arg:
        return resolve_project_path(input_arg)

    families_dir = resolve_project_path("data/data_input/families")
    if families_dir.exists():
        return families_dir

    normalized_dir = resolve_project_path("data/data_input/normalized")
    if normalized_dir.exists():
        return normalized_dir

    input_dir = resolve_project_path("data/data_input")
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
