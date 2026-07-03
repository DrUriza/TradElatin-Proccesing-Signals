from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class OutputValidator:
    OFFICIAL_FAMILIES = [
        "prices_ohlcv",
        "volume_orderflow",
        "liquidity_microstructure",
        "institutional_flows",
        "liquidations",
        "derivatives_open_interest",
        "sentiment_positioning",
        "on_chain_miners",
        "options_volatility",
    ]
    REQUIRED_PAYLOAD_KEYS = {
        "pipeline",
        "version",
        "family_key",
        "output_shape",
        "records_processed",
        "symbols",
        "timeframes",
        "data_types",
        "blocks",
    }
    COMPLETE_BLOCK_KEYS = {
        "source_name",
        "detected",
        "normalized",
        "decision",
        "math",
        "patterns",
        "routes",
        "family_key",
        "output_shape",
    }
    SPECIALIZED_SHAPES = {
        "bars",
        "event_list",
        "regimes",
        "candlestick_derived",
        "cvd_candlestick_derived",
        "orderbook",
        "orderflow_features",
        "volume_features",
    }
    FULL_STATISTICS_ALLOWED = {"time_series", "candlestick", "candlestick_derived", "cvd_candlestick_derived"}
    FULL_REGIMES_ALLOWED = {"time_series", "candlestick", "candlestick_derived", "cvd_candlestick_derived", "regimes"}
    FULL_TECHNICAL_ALLOWED = {"candlestick", "candlestick_derived", "cvd_candlestick_derived"}
    TECHNICAL_FORBIDDEN = {"bars", "event_list", "regimes", "orderflow_features", "volume_features"}

    def __init__(self, output_root: Path):
        self.output_root = Path(output_root)
        self.families_root = self.output_root / "families"
        self.metadata_root = self.output_root / "metadata"

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        warnings: list[str] = []
        family_reports: list[dict[str, Any]] = []

        if not self.families_root.exists():
            errors.append(f"Families root not found: {self.families_root}")
        if (self.output_root / "statistics").exists():
            errors.append("Global statistics output folder is not allowed; statistics must live under block math.statistics.")

        family_dirs = [path for path in self.families_root.iterdir() if path.is_dir()] if self.families_root.exists() else []
        found_families = {path.name for path in family_dirs}
        official_family_set = set(self.OFFICIAL_FAMILIES)
        inactive_families = [family for family in self.OFFICIAL_FAMILIES if family not in found_families]
        unexpected_families = sorted(found_families - official_family_set)

        for family_key in unexpected_families:
            errors.append(f"Unexpected family folder: {family_key}")

        if (self.families_root / "manifest").exists():
            errors.append("Manifest must not be written under src/processing_signals/output/families/manifest.")

        for family_dir in sorted(family_dirs):
            json_files = sorted(family_dir.glob("*.json"))
            if len(json_files) > 4:
                errors.append(f"Family {family_dir.name} has more than 4 JSON outputs.")

            output_reports = []
            for json_path in json_files:
                output_reports.append(self._validate_family_file(json_path, family_dir.name, errors, warnings))

            family_reports.append(
                {
                    "family_key": family_dir.name,
                    "json_count": len(json_files),
                    "outputs": output_reports,
                }
            )

        metadata_report = self._validate_metadata(self.metadata_root / "manifest.json", errors, warnings)

        report = {
            "status": "ok" if not errors else "failed",
            "errors": errors,
            "warnings": warnings,
            "families_root": str(self.families_root),
            "metadata_root": str(self.metadata_root),
            "official_families": self.OFFICIAL_FAMILIES,
            "active_families": [family for family in self.OFFICIAL_FAMILIES if family in found_families],
            "inactive_families": inactive_families,
            "families_found": sorted(found_families),
            "missing_families": inactive_families,
            "unexpected_families": unexpected_families,
            "families": family_reports,
            "metadata": metadata_report,
        }
        return report

    def write_report(self, report_path: Path | None = None) -> dict[str, Any]:
        report = self.validate()
        output_path = Path(report_path) if report_path else self.output_root / "validation_report.json"
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, default=str)
        return report

    def _validate_family_file(
        self,
        json_path: Path,
        expected_family_key: str,
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, Any]:
        payload = self._read_json(json_path, errors)
        if payload is None:
            return {"path": str(json_path), "status": "failed"}

        missing_keys = sorted(self.REQUIRED_PAYLOAD_KEYS - set(payload.keys()))
        for key in missing_keys:
            errors.append(f"{json_path}: missing payload key {key}")

        family_key = payload.get("family_key")
        output_shape = payload.get("output_shape")
        blocks = payload.get("blocks", [])
        status = payload.get("status")

        if family_key != expected_family_key:
            errors.append(f"{json_path}: family_key {family_key!r} does not match folder {expected_family_key!r}")
        if output_shape != json_path.stem:
            errors.append(f"{json_path}: output_shape {output_shape!r} does not match filename {json_path.stem!r}")
        if not isinstance(blocks, list):
            errors.append(f"{json_path}: blocks must be a list")
            blocks = []
        if not blocks and status != "pending_builder":
            errors.append(f"{json_path}: blocks is empty and status is not pending_builder")

        block_reports = [
            self._validate_block(json_path, block, family_key, output_shape, errors, warnings)
            for block in blocks
        ]

        return {
            "path": str(json_path),
            "status": "ok",
            "output_shape": output_shape,
            "records_processed": payload.get("records_processed"),
            "symbols": payload.get("symbols", []),
            "timeframes": payload.get("timeframes", []),
            "data_types": payload.get("data_types", {}),
            "blocks_count": len(blocks),
            "block_issues": [issue for issue in block_reports if issue],
        }

    def _validate_block(
        self,
        json_path: Path,
        block: Any,
        family_key: str,
        output_shape: str,
        errors: list[str],
        warnings: list[str],
    ) -> dict[str, Any] | None:
        if not isinstance(block, dict):
            errors.append(f"{json_path}: block is not an object")
            return {"error": "block_not_object"}

        if output_shape not in self.SPECIALIZED_SHAPES:
            missing_keys = sorted(self.COMPLETE_BLOCK_KEYS - set(block.keys()))
            for key in missing_keys:
                errors.append(f"{json_path}: block {block.get('source_name')} missing key {key}")

        if block.get("family_key") != family_key:
            errors.append(f"{json_path}: block {block.get('source_name')} has wrong family_key {block.get('family_key')!r}")
        if not block.get("source_name"):
            errors.append(f"{json_path}: block missing source_name")

        if output_shape in self.SPECIALIZED_SHAPES:
            self._validate_specialized_block(json_path, block, output_shape, errors)
            feature_snapshot = block.get("feature_snapshot", {})
        else:
            if not isinstance(block.get("detected"), dict):
                errors.append(f"{json_path}: block {block.get('source_name')} detected must be an object")

            math_payload = block.get("math")
            if not isinstance(math_payload, dict):
                errors.append(f"{json_path}: block {block.get('source_name')} math must be an object")
                math_payload = {}
            if output_shape in self.FULL_STATISTICS_ALLOWED and "statistics" not in math_payload:
                errors.append(f"{json_path}: block {block.get('source_name')} missing math.statistics")
            if output_shape in self.FULL_REGIMES_ALLOWED and "statistical_regimes" not in math_payload:
                errors.append(f"{json_path}: block {block.get('source_name')} missing math.statistical_regimes")
            if math_payload.get("statistical_regimes") and "regime_flags" not in math_payload.get("statistical_regimes", {}):
                errors.append(f"{json_path}: block {block.get('source_name')} missing math.statistical_regimes.regime_flags")
            self._validate_math_contract(json_path, block, output_shape, errors)
            feature_snapshot = block.get("math", {}).get("feature_snapshot", {})

        non_numeric = [
            key
            for key, value in feature_snapshot.items()
            if value is not None and not isinstance(value, (int, float))
        ]
        if non_numeric:
            warnings.append(f"{json_path}: block {block.get('source_name')} has non-numeric feature_snapshot keys {non_numeric}")

        return None

    def _validate_specialized_block(
        self,
        json_path: Path,
        block: dict[str, Any],
        output_shape: str,
        errors: list[str],
    ) -> None:
        forbidden_keys = {"normalized", "patterns", "decision", "routes"}
        present_forbidden = sorted(forbidden_keys & set(block))
        if present_forbidden:
            errors.append(f"{json_path}: specialized block {block.get('source_name')} has forbidden keys {present_forbidden}")

        if output_shape in {"bars"} and "bars" not in block:
            errors.append(f"{json_path}: bars block {block.get('source_name')} missing bars")
        if output_shape in {"event_list"} and "events" not in block:
            errors.append(f"{json_path}: event_list block {block.get('source_name')} missing events")
        if output_shape in {"regimes"} and "regimes" not in block:
            errors.append(f"{json_path}: regimes block {block.get('source_name')} missing regimes")
        if output_shape in {"candlestick_derived", "cvd_candlestick_derived"} and "candles" not in block:
            errors.append(f"{json_path}: candlestick_derived block {block.get('source_name')} missing candles")
        if output_shape in {"volume_features", "orderflow_features"} and "feature_snapshot" not in block:
            errors.append(f"{json_path}: feature block {block.get('source_name')} missing feature_snapshot")
        if output_shape == "volume_features":
            derived_from = block.get("derived_from", {})
            if block.get("source_family_key") != "prices_ohlcv":
                errors.append(f"{json_path}: volume_features block {block.get('source_name')} missing prices_ohlcv source_family_key")
            if derived_from.get("family_key") != "prices_ohlcv":
                errors.append(f"{json_path}: volume_features block {block.get('source_name')} missing derived_from prices_ohlcv")

        regime_flags = block.get("regime_flags")
        if not isinstance(regime_flags, dict):
            errors.append(f"{json_path}: specialized block {block.get('source_name')} missing regime_flags")

        self._validate_math_contract(json_path, block, output_shape, errors)

    def _validate_math_contract(
        self,
        json_path: Path,
        block: dict[str, Any],
        output_shape: str,
        errors: list[str],
    ) -> None:
        math_payload = block.get("math", {}) or {}
        if not isinstance(math_payload, dict):
            errors.append(f"{json_path}: block {block.get('source_name')} math must be an object when present")
            return

        has_statistics = bool(math_payload.get("statistics"))
        has_regimes = bool(math_payload.get("statistical_regimes"))
        has_technical = bool(math_payload.get("technical_indicators"))

        if has_statistics and output_shape not in self.FULL_STATISTICS_ALLOWED:
            errors.append(f"{json_path}: {output_shape} must not contain full math.statistics")
        if has_regimes and output_shape not in self.FULL_REGIMES_ALLOWED:
            errors.append(f"{json_path}: {output_shape} must not contain full math.statistical_regimes")
        if has_technical and output_shape not in self.FULL_TECHNICAL_ALLOWED:
            if not (output_shape == "time_series" and self._is_ohlc_compatible(block)):
                errors.append(f"{json_path}: {output_shape} must not contain full technical_indicators")

        if output_shape in self.TECHNICAL_FORBIDDEN and ("technical_indicators" in block or has_technical):
            errors.append(f"{json_path}: {output_shape} forbids technical_indicators")
        if output_shape in {"bars", "event_list", "regimes"} and self._contains_key(block, "dataframe"):
            errors.append(f"{json_path}: {output_shape} must not contain normalized.dataframe")
        if self._is_feature_shape(output_shape) and self._contains_key(block, "dataframe"):
            errors.append(f"{json_path}: feature files must not contain full dataframe")

    @staticmethod
    def _is_feature_shape(output_shape: str) -> bool:
        return output_shape.endswith("_features") or output_shape in {"volume_features", "orderflow_features"}

    @staticmethod
    def _contains_key(value: Any, key: str) -> bool:
        if isinstance(value, dict):
            return key in value or any(OutputValidator._contains_key(item, key) for item in value.values())
        if isinstance(value, list):
            return any(OutputValidator._contains_key(item, key) for item in value)
        return False

    @staticmethod
    def _is_ohlc_compatible(block: dict[str, Any]) -> bool:
        normalized = block.get("normalized", {})
        dataframe = normalized.get("dataframe")
        if isinstance(dataframe, list) and dataframe:
            return {"timestamp", "open", "high", "low", "close"}.issubset(set(dataframe[0]))
        return False

    def _validate_metadata(self, manifest_path: Path, errors: list[str], warnings: list[str]) -> list[dict[str, Any]]:
        if not manifest_path.exists():
            return []

        payload = self._read_json(manifest_path, errors)
        if payload is None:
            return [{"path": str(manifest_path), "status": "failed"}]

        blocks = payload.get("blocks", [])
        if not blocks:
            errors.append(f"{manifest_path}: manifest metadata has no blocks")

        return [
            {
                "path": str(manifest_path),
                "status": "ok",
                "output_shape": payload.get("output_shape"),
                "records_processed": payload.get("records_processed"),
                "blocks_count": len(blocks) if isinstance(blocks, list) else 0,
            }
        ]

    @staticmethod
    def _read_json(path: Path, errors: list[str]) -> dict[str, Any] | None:
        try:
            with path.open("r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{path}: failed to read JSON: {exc}")
            return None

        if not isinstance(payload, dict):
            errors.append(f"{path}: JSON root must be an object")
            return None
        return payload
