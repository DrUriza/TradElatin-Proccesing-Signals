from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import shutil
from typing import Any

import pandas as pd


class FamilyOutputBuilder:
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

    def __init__(self, output_dir: Path, pipeline_name: str, version: str):
        self.output_dir = Path(output_dir)
        self.metadata_dir = self.output_dir.parent / "metadata"
        self.pipeline_name = pipeline_name
        self.version = version

    def write_family_outputs(self, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        self._prepare_output_roots()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)

        for block in blocks:
            family_key = block.get("family_key", "unknown")
            output_shape = block.get("output_shape", "unknown")

            if block.get("is_metadata"):
                block["family_output_path"] = ""
                continue

            if family_key not in self.OFFICIAL_FAMILIES:
                continue

            if family_key == "liquidity_microstructure":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._liquidity_variants(block) or self._single_shape_variant(block):
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "prices_ohlcv":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._prices_variants(block) or self._single_shape_variant(block):
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                for variant_shape, variant_filename in self._volume_derivative_variants(block):
                    output_path = self.output_dir / "volume_orderflow" / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[("volume_orderflow", variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "volume_orderflow":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._volume_orderflow_variants(block) or self._single_shape_variant(block):
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key in {"institutional_flows", "liquidations"}:
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._four_shape_variants():
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "derivatives_open_interest":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._open_interest_variants():
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "sentiment_positioning":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._sentiment_variants():
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "on_chain_miners":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._network_onchain_variants():
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            elif family_key == "options_volatility":
                block["family_output_paths"] = []
                for variant_shape, variant_filename in self._single_shape_variant(block):
                    output_path = self.output_dir / family_key / variant_filename
                    block["family_output_paths"].append(str(output_path))
                    grouped[(family_key, variant_shape)].append(block)
                block["family_output_path"] = block["family_output_paths"][0] if block["family_output_paths"] else ""
            else:
                output_filename = block.get("output_filename", f"{output_shape}.json")
                output_path = self.output_dir / family_key / output_filename
                block["family_output_path"] = str(output_path)
                grouped[(family_key, output_shape)].append(block)

        self._validate_family_output_limits(grouped)

        family_entries: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for (family_key, output_shape), family_blocks in sorted(grouped.items()):
            family_dir = self.output_dir / family_key
            family_dir.mkdir(parents=True, exist_ok=True)
            output_filename = f"{output_shape}.json"
            output_path = family_dir / output_filename
            payload = self._build_family_payload(family_key, output_shape, family_blocks)
            self._write_json(payload, output_path)
            family_entries[family_key].append(
                {
                    "output_shape": output_shape,
                    "path": str(output_path),
                    "records_processed": len(family_blocks),
                }
            )

        active_families = [family for family in self.OFFICIAL_FAMILIES if family in family_entries]
        inactive_families = [family for family in self.OFFICIAL_FAMILIES if family not in family_entries]

        return {
            "families_root": str(self.output_dir),
            "official_families": self.OFFICIAL_FAMILIES,
            "active_families": active_families,
            "inactive_families": inactive_families,
            "families": [
                {"family_key": family_key, "outputs": family_entries[family_key]}
                for family_key in self.OFFICIAL_FAMILIES
                if family_key in family_entries
            ],
        }

    def _prepare_output_roots(self) -> None:
        for path in [self.output_dir, self.metadata_dir]:
            if path.exists():
                shutil.rmtree(path)

    def _build_family_payload(
        self,
        family_key: str,
        output_shape: str,
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        serializable_blocks = [
            self._serialize_block_for_shape(family_key, output_shape, block)
            for block in blocks
        ]
        payload = {
            "pipeline": self.pipeline_name,
            "version": self.version,
            "family_key": family_key,
            "output_shape": output_shape,
            "records_processed": len(serializable_blocks),
            "symbols": self._unique_values(serializable_blocks, "symbol"),
            "timeframes": self._unique_values(serializable_blocks, "timeframe"),
            "data_types": self._count_data_types(serializable_blocks),
            "blocks": serializable_blocks,
        }
        if self._is_complete_shape(family_key, output_shape):
            payload["ml_feature_matrix_preview"] = self._build_ml_feature_matrix_preview(serializable_blocks)
        if output_shape == "regimes":
            payload["statistical_regimes_summary"] = self._build_statistical_regimes_summary(serializable_blocks)
        if output_shape == "volume_features":
            payload.update(
                {
                    "derived_from_family": "prices_ohlcv",
                    "derived_from_data_type": "candlestick",
                    "derived_feature_family": "volume_orderflow",
                }
            )
        return payload

    def _build_metadata_payload(self, output_shape: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        serializable_blocks = [self._to_json_safe(block) for block in blocks]
        return {
            "pipeline": self.pipeline_name,
            "version": self.version,
            "output_shape": output_shape,
            "records_processed": len(serializable_blocks),
            "blocks": serializable_blocks,
        }

    def _serialize_block_for_shape(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        if output_shape in {"bars"}:
            return self.serialize_bars_view(family_key, output_shape, block)
        if output_shape in {"event_list"}:
            return self.serialize_event_list_view(family_key, output_shape, block)
        if output_shape in {"regimes"}:
            return self.serialize_regimes_view(family_key, output_shape, block)
        if output_shape in {"candlestick_derived", "cvd_candlestick_derived"}:
            return self.serialize_candlestick_derived_view(family_key, output_shape, block)
        if output_shape == "candlestick":
            return self.serialize_candlestick_view(family_key, output_shape, block)
        if output_shape in {"orderbook"}:
            return self.serialize_orderbook_view(family_key, output_shape, block)
        if self._is_feature_shape(output_shape):
            return self.serialize_feature_view(family_key, output_shape, block)
        if family_key == "liquidity_microstructure" and output_shape == "time_series":
            return self.serialize_time_series_view(family_key, output_shape, block, include_orderbook_depth=False)
        return self.serialize_time_series_view(family_key, output_shape, block, include_orderbook_depth=True)

    def serialize_time_series_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
        include_orderbook_depth: bool = True,
    ) -> dict[str, Any]:
        normalized = dict(block.get("normalized", {}))

        if not include_orderbook_depth:
            normalized.pop("bids", None)
            normalized.pop("asks", None)

        view = self._complete_block_header(family_key, output_shape, block)
        view.update(
            {
                "detected": block.get("detected", {}),
                "normalized": normalized,
                "vectorized": block.get("vectorized", {}),
                "transforms": self._transform_summary(block),
                "decision": block.get("decision", {}),
                "math": self.build_math_for_view(block, output_shape),
                "patterns": block.get("patterns", {}),
                "view_patterns": self._view_patterns_for_shape(block, output_shape),
                "routes": block.get("routes", {}),
            }
        )
        return self._to_json_safe(view)

    def serialize_candlestick_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        view = self._complete_block_header(family_key, output_shape, block)
        view.update(
            {
                "detected": block.get("detected", {}),
                "normalized": block.get("normalized", {}),
                "vectorized": block.get("vectorized", {}),
                "transforms": self._transform_summary(block),
                "decision": block.get("decision", {}),
                "math": self.build_math_for_view(block, output_shape),
                "patterns": block.get("patterns", {}),
                "routes": block.get("routes", {}),
            }
        )
        return self._to_json_safe(view)

    def serialize_bars_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        df = self._dataframe(block)
        reference_column = self._reference_column(block, df)
        transform_view = block.get("transforms", {}).get("bars", {})
        bars = transform_view.get("records") or self._records_from_bar_columns(df, reference_column)
        reference_column = transform_view.get("reference_column") or reference_column
        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "bar_schema": {
                    "timestamp": "datetime",
                    "open": "float",
                    "high": "float",
                    "low": "float",
                    "close": "float",
                    "volume": "optional",
                },
                "bars": bars,
                "summary": {
                    "rows": len(bars),
                    "source_rows": self._source_rows(block),
                    "reference_column": reference_column,
                },
                "math_summary": self._compact_math_summary(block),
                "math": self.build_math_for_view(block, output_shape),
            }
        )
        return self._to_json_safe(header)

    def serialize_event_list_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        events_df = block.get("normalized", {}).get("events")
        if isinstance(events_df, pd.DataFrame):
            events = self._native_events(family_key, block, events_df)
        else:
            events = block.get("transforms", {}).get("event_list", {}).get("events") or self._significant_events(family_key, block)

        counts_by_type: dict[str, int] = {}
        counts_by_severity: dict[str, int] = {}
        for event in events:
            event_type = event.get("event_type", "unknown")
            severity = event.get("severity", "unknown")
            counts_by_type[event_type] = counts_by_type.get(event_type, 0) + 1
            counts_by_severity[severity] = counts_by_severity.get(severity, 0) + 1

        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "events": events,
                "event_summary": {
                    "events": len(events),
                    "source_rows": self._source_rows(block),
                },
                "event_counts": {
                    "by_type": counts_by_type,
                    "by_severity": counts_by_severity,
                },
                "event_counts_by_type": counts_by_type,
                "event_counts_by_severity": counts_by_severity,
                "math_summary": self._compact_math_summary(block),
                "math": self.build_math_for_view(block, output_shape),
            }
        )
        return self._to_json_safe(header)

    def serialize_regimes_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        regimes = block.get("math", {}).get("statistical_regimes", {}) or {}
        detected = block.get("detected", {})
        math_for_view = self.build_math_for_view(block, output_shape)
        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "detected": {
                    "data_type": detected.get("data_type"),
                    "canonical_type": detected.get("canonical_type"),
                    "symbol": detected.get("symbol"),
                    "timeframe": detected.get("timeframe"),
                    "provider_source": detected.get("provider_source"),
                },
                "regimes": math_for_view.get("statistical_regimes", {}),
                "math": math_for_view,
                "numeric_columns": regimes.get("numeric_columns", []),
                "windows": regimes.get("windows", []),
                "last": regimes.get("last", {}),
                "last_regimes": regimes.get("last_regimes", {}),
                "regime_summary": {
                    "numeric_columns": len(regimes.get("numeric_columns", [])),
                    "windows": regimes.get("windows", []),
                    "last_regime_count": len(regimes.get("last_regimes", {}) or {}),
                },
                "summary": {
                    "rows": self._source_rows(block),
                    "windows": regimes.get("windows", []),
                    "numeric_columns": regimes.get("numeric_columns", []),
                },
            }
        )
        return self._to_json_safe(header)

    def serialize_candlestick_derived_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        df = self._dataframe(block)
        reference_column = self._reference_column(block, df)
        transform_view = block.get("transforms", {}).get("candlestick_derived", {})
        candles = transform_view.get("records") or self._records_from_bar_columns(df, reference_column)
        conversion = transform_view.get("conversion") or {
            "method": "numeric_series_to_ohlc",
            "reference_column": reference_column,
            "source_rows": self._source_rows(block),
            "derived_rows": len(candles),
        }
        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "source_data_type": block.get("detected", {}).get("data_type"),
                "conversion": conversion,
                "candles": candles,
                "summary": {
                    "rows": len(candles),
                    "source_rows": self._source_rows(block),
                    "reference_column": conversion.get("reference_column"),
                },
                "view_patterns": self._view_patterns_for_shape(block, output_shape),
                "math_summary": self._compact_math_summary(block),
                "math": self.build_math_for_view(block, output_shape),
            }
        )
        return self._to_json_safe(header)

    def serialize_orderbook_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = block.get("normalized", {})
        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "summary": normalized.get("summary", {}),
                "bids": normalized.get("bids", pd.DataFrame()),
                "asks": normalized.get("asks", pd.DataFrame()),
                "microstructure": block.get("math", {}).get("microstructure", {}),
                "liquidity_metrics": block.get("math", {}).get("feature_snapshot", {}),
                "math_summary": self._compact_math_summary(block),
                "math": self.build_math_for_view(block, output_shape),
            }
        )
        dataframe = normalized.get("dataframe")
        if isinstance(dataframe, pd.DataFrame):
            header["orderbook_snapshots"] = dataframe
        return self._to_json_safe(header)

    def serialize_feature_view(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        statistics = block.get("math", {}).get("statistics", {}) or {}
        feature_snapshot = block.get("math", {}).get("feature_snapshot", {}) or {}
        header = self._compact_block_header(family_key, output_shape, block)
        header.update(
            {
                "feature_inventory": {
                    "feature_count": len(feature_snapshot),
                    "feature_names": sorted(feature_snapshot),
                },
                "feature_snapshot": feature_snapshot,
                "numeric_columns": statistics.get("numeric_columns", []),
                "selected_features": sorted(feature_snapshot),
                "selected_feature_columns": sorted(feature_snapshot),
                "windows": statistics.get("windows", []),
                "rows": self._source_rows(block),
                "source_rows": self._source_rows(block),
                "source_references": {
                    "source_name": block.get("source_name"),
                    "source_family_key": self._source_family_key(block),
                    "source_data_type": block.get("detected", {}).get("data_type"),
                },
                "derived_from": {
                    "family_key": self._source_family_key(block),
                    "data_type": block.get("detected", {}).get("data_type"),
                    "source_name": block.get("source_name"),
                },
                "math": self.build_math_for_view(block, output_shape),
            }
        )
        if output_shape == "volume_features":
            header["source_family_key"] = "prices_ohlcv"
            header["family_key"] = "volume_orderflow"
            header["derived_from"] = {
                "family_key": "prices_ohlcv",
                "data_type": "candlestick",
                "source_columns": [
                    "volume",
                    "notional_volume",
                    "open",
                    "high",
                    "low",
                    "close",
                ],
                "reason": "Volume/orderflow features derived from OHLCV volume fields.",
            }
        return self._to_json_safe(header)

    @classmethod
    def _is_complete_shape(cls, family_key: str, output_shape: str) -> bool:
        if output_shape in {"candlestick", "time_series", "cvd_time_series"}:
            return not (family_key == "liquidity_microstructure" and output_shape == "time_series")
        return False

    @staticmethod
    def _is_feature_shape(output_shape: str) -> bool:
        return output_shape.endswith("_features") or output_shape in {"volume_features", "orderflow_features"}

    def build_math_for_view(self, block: dict[str, Any], output_shape: str) -> dict[str, Any]:
        """Return only the math sections allowed by the official Section 4 contract."""
        math_payload = block.get("math", {}) or {}
        regimes = math_payload.get("statistical_regimes", {}) or {}
        view_math = block.get("view_math", {}) or {}
        allowed: dict[str, Any] = {}

        if output_shape in {"time_series", "candlestick", "candlestick_derived", "cvd_candlestick_derived"}:
            if output_shape != "cvd_time_series":
                technical = self._technical_for_output_shape(math_payload, view_math, output_shape)
                if technical:
                    allowed["technical_indicators"] = technical
            if math_payload.get("statistics"):
                allowed["statistics"] = math_payload["statistics"]
            if regimes:
                allowed["statistical_regimes"] = regimes
            if math_payload.get("microstructure"):
                allowed["microstructure"] = math_payload["microstructure"]
            if math_payload.get("feature_snapshot"):
                allowed["feature_snapshot"] = math_payload["feature_snapshot"]
            if math_payload.get("warnings"):
                allowed["warnings"] = math_payload["warnings"]
            return allowed

        if output_shape == "regimes":
            allowed["statistical_regimes"] = {
                "numeric_columns": regimes.get("numeric_columns", []),
                "windows": regimes.get("windows", []),
                "last": regimes.get("last", {}),
                "last_regimes": regimes.get("last_regimes", {}),
                "regime_flags": regimes.get("regime_flags", self._empty_regime_flags()),
            }
            return allowed

        if output_shape in {"bars", "event_list"} or self._is_feature_shape(output_shape):
            allowed["regime_flags"] = self._regime_flags(block)
            if math_payload.get("microstructure") and output_shape == "event_list":
                allowed["microstructure_summary"] = {
                    key: value
                    for key, value in math_payload.get("microstructure", {}).items()
                    if isinstance(value, (int, float, str, bool)) or value is None
                }
            return allowed

        if output_shape == "orderbook":
            allowed["regime_flags"] = self._regime_flags(block)
            if math_payload.get("microstructure"):
                allowed["microstructure"] = math_payload["microstructure"]
            return allowed

        return {"regime_flags": self._regime_flags(block)}

    @staticmethod
    def _technical_for_output_shape(
        math_payload: dict[str, Any],
        view_math: dict[str, Any],
        output_shape: str,
    ) -> dict[str, Any]:
        if output_shape in {"candlestick", "time_series"}:
            return math_payload.get("technical_indicators", {}) or {}
        if output_shape in {"candlestick_derived", "cvd_candlestick_derived"}:
            return view_math.get("candlestick_derived", {}).get("technical_indicators", {}) or {}
        return {}

    def _complete_block_header(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        detected = block.get("detected", {})
        return {
            "source_name": block.get("source_name"),
            "family_key": family_key,
            "source_family_key": self._source_family_key(block),
            "output_shape": output_shape,
            "output_filename": block.get("output_filename"),
            "output_file_key": block.get("output_file_key"),
            "is_metadata": block.get("is_metadata", False),
            "family_output_path": block.get("family_output_path"),
            "family_output_paths": block.get("family_output_paths", []),
            "symbol": detected.get("symbol"),
            "timeframe": detected.get("timeframe"),
            "data_type": detected.get("data_type"),
            "regime_flags": self._regime_flags(block),
        }

    def _compact_block_header(
        self,
        family_key: str,
        output_shape: str,
        block: dict[str, Any],
    ) -> dict[str, Any]:
        detected = block.get("detected", {})
        return {
            "source_name": block.get("source_name"),
            "family_key": family_key,
            "source_family_key": self._source_family_key(block),
            "output_shape": output_shape,
            "symbol": detected.get("symbol"),
            "timeframe": detected.get("timeframe"),
            "data_type": detected.get("data_type"),
            "source_subtype": block.get("source_subtype"),
            "regime_flags": self._regime_flags(block),
            "warnings": block.get("math", {}).get("warnings", []),
        }

    @staticmethod
    def _view_patterns_for_shape(block: dict[str, Any], output_shape: str) -> dict[str, Any]:
        view_patterns = block.get("patterns", {}).get("view_patterns", {}) or {}
        if output_shape == "time_series":
            return view_patterns
        if output_shape in {"candlestick_derived", "cvd_candlestick_derived"}:
            return view_patterns.get(output_shape) or view_patterns.get("candlestick_derived", {})
        return {}

    @staticmethod
    def _transform_summary(block: dict[str, Any]) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for shape, transform in (block.get("transforms", {}) or {}).items():
            if not isinstance(transform, dict):
                continue
            records = transform.get("records")
            events = transform.get("events")
            summary[shape] = {
                "records": len(records) if isinstance(records, list) else None,
                "events": len(events) if isinstance(events, list) else None,
                "reference_column": transform.get("reference_column"),
                "conversion": transform.get("conversion"),
            }
        return summary

    @staticmethod
    def _source_family_key(block: dict[str, Any]) -> str | None:
        return (
            block.get("detected", {})
            .get("metadata", {})
            .get("family")
            or block.get("family_key")
        )

    @staticmethod
    def _dataframe(block: dict[str, Any]) -> pd.DataFrame:
        dataframe = block.get("normalized", {}).get("dataframe")
        if isinstance(dataframe, pd.DataFrame):
            return dataframe.copy()
        return pd.DataFrame()

    @staticmethod
    def _source_rows(block: dict[str, Any]) -> int:
        summary = block.get("normalized", {}).get("summary", {}) or {}
        rows = summary.get("rows")
        if isinstance(rows, int):
            return rows
        dataframe = block.get("normalized", {}).get("dataframe")
        if isinstance(dataframe, pd.DataFrame):
            return len(dataframe)
        events = block.get("normalized", {}).get("events")
        if isinstance(events, pd.DataFrame):
            return len(events)
        return 0

    @classmethod
    def _reference_column(cls, block: dict[str, Any], df: pd.DataFrame) -> str | None:
        reference = block.get("math", {}).get("statistics", {}).get("reference_column")
        if reference in df.columns:
            return reference
        for candidate in ["close", "value", "open_interest_usd", "long_short_ratio", "exchange_netflow", "total_liquidations_usd"]:
            if candidate in df.columns:
                return candidate
        numeric_columns = block.get("math", {}).get("statistics", {}).get("numeric_columns", [])
        for column in numeric_columns:
            if column in df.columns:
                return column
        numeric_df = df.select_dtypes(include="number")
        if not numeric_df.empty:
            return str(numeric_df.columns[0])
        return None

    @classmethod
    def _records_from_bar_columns(cls, df: pd.DataFrame, reference_column: str | None) -> list[dict[str, Any]]:
        if df.empty:
            return []

        records: list[dict[str, Any]] = []
        has_ohlc = all(column in df.columns for column in ["open", "high", "low", "close"])
        for _, row in df.iterrows():
            record = {
                "timestamp": row.get("timestamp"),
            }
            if has_ohlc:
                record.update(
                    {
                        "open": row.get("open"),
                        "high": row.get("high"),
                        "low": row.get("low"),
                        "close": row.get("close"),
                    }
                )
            elif reference_column and reference_column in df.columns:
                value = row.get(reference_column)
                record.update(
                    {
                        "open": value,
                        "high": value,
                        "low": value,
                        "close": value,
                    }
                )
            else:
                continue

            if "volume" in df.columns:
                record["volume"] = row.get("volume")
            elif "notional_volume" in df.columns:
                record["volume"] = row.get("notional_volume")
            else:
                record["volume"] = None
            records.append(record)
        return records

    def _native_events(
        self,
        family_key: str,
        block: dict[str, Any],
        events_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        detected = block.get("detected", {})
        events: list[dict[str, Any]] = []
        for _, row in events_df.iterrows():
            direction = row.get("side") or row.get("direction") or row.get("aggressor_side")
            value = row.get("notional_usdt") or row.get("value") or row.get("quantity_btc")
            events.append(
                {
                    "timestamp": row.get("timestamp"),
                    "symbol": row.get("symbol", detected.get("symbol")),
                    "timeframe": row.get("timeframe", detected.get("timeframe")),
                    "family_key": family_key,
                    "data_type": detected.get("data_type"),
                    "event_type": row.get("event_type", detected.get("data_type")),
                    "metric": "notional_usdt" if "notional_usdt" in events_df.columns else "value",
                    "value": value,
                    "severity": self._severity(value),
                    "direction": direction,
                    "reason": "native event record",
                    "source_name": block.get("source_name"),
                }
            )
        return events

    def _significant_events(self, family_key: str, block: dict[str, Any]) -> list[dict[str, Any]]:
        df = self._dataframe(block)
        if df.empty:
            return []

        detected = block.get("detected", {})
        numeric_columns = [
            column
            for column in block.get("math", {}).get("statistics", {}).get("numeric_columns", [])
            if column in df.columns
        ]
        events: list[dict[str, Any]] = []
        for column in numeric_columns:
            series = pd.to_numeric(df[column], errors="coerce")
            std = series.std()
            if pd.isna(std) or std == 0:
                continue
            zscores = (series - series.mean()) / std
            significant = zscores[zscores.abs() >= 2.0].abs().sort_values(ascending=False).head(25)
            for index in significant.index:
                zscore = zscores.loc[index]
                row = df.loc[index]
                direction = "positive" if zscore >= 0 else "negative"
                events.append(
                    {
                        "timestamp": row.get("timestamp"),
                        "symbol": row.get("symbol", detected.get("symbol")),
                        "timeframe": row.get("timeframe", detected.get("timeframe")),
                        "family_key": family_key,
                        "data_type": detected.get("data_type"),
                        "event_type": self._event_type(family_key, detected.get("data_type"), column, direction),
                        "metric": column,
                        "value": row.get(column),
                        "severity": "high" if abs(zscore) >= 3.0 else "medium",
                        "direction": direction,
                        "reason": f"zscore {'>=' if zscore >= 0 else '<='} {round(float(zscore), 4)}",
                        "source_name": block.get("source_name"),
                    }
                )
        events.sort(key=lambda event: (str(event.get("timestamp")), event.get("metric", "")))
        return events[:150]

    @staticmethod
    def _severity(value: Any) -> str:
        if isinstance(value, (int, float)) and abs(value) >= 1_000_000:
            return "high"
        return "medium"

    @staticmethod
    def _event_type(family_key: str, data_type: str | None, metric: str, direction: str) -> str:
        if family_key == "liquidations":
            return "liquidation_spike"
        if family_key == "institutional_flows" and "netflow" in metric:
            return "exchange_netflow_spike"
        if family_key == "on_chain_miners":
            return "miner_pressure_event"
        if family_key == "options_volatility":
            return "volatility_event"
        if direction == "positive":
            return "outlier_positive"
        return "outlier_negative"

    @staticmethod
    def _regime_flags(block: dict[str, Any]) -> dict[str, bool]:
        return (
            block.get("math", {})
            .get("statistical_regimes", {})
            .get("regime_flags")
            or FamilyOutputBuilder._empty_regime_flags()
        )

    @staticmethod
    def _empty_regime_flags() -> dict[str, bool]:
        return {
            "high_volatility_regime": False,
            "low_volatility_regime": False,
            "trend_expansion": False,
            "mean_reversion_zone": False,
            "outlier_positive": False,
            "outlier_negative": False,
            "distribution_skewed_positive": False,
            "distribution_skewed_negative": False,
            "fat_tail_risk": False,
        }

    @staticmethod
    def _compact_math_summary(block: dict[str, Any]) -> dict[str, Any]:
        math_payload = block.get("math", {})
        statistics = math_payload.get("statistics", {}) or {}
        regimes = math_payload.get("statistical_regimes", {}) or {}
        feature_snapshot = math_payload.get("feature_snapshot", {}) or {}
        numeric_columns = statistics.get("numeric_columns", []) or []
        return {
            "has_statistics": bool(statistics),
            "statistics_windows": statistics.get("windows", []),
            "numeric_columns_count": len(numeric_columns),
            "reference_column": statistics.get("reference_column"),
            "has_statistical_regimes": bool(regimes),
            "regime_windows": regimes.get("windows", []),
            "last_regime_count": len(regimes.get("last_regimes", {}) or {}),
            "has_feature_snapshot": bool(feature_snapshot),
            "feature_count": len(feature_snapshot),
        }

    @staticmethod
    def _liquidity_variants(block: dict[str, Any]) -> list[tuple[str, str]]:
        data_type = block.get("detected", {}).get("data_type")
        subtype_by_data_type = {
            "orderbook_conventional": "conventional",
            "orderbook_large_trades": "large_trades",
            "orderbook_whale_orders": "whale_orders",
        }
        subtype = subtype_by_data_type.get(data_type)
        if subtype is None:
            return []
        block["source_subtype"] = subtype

        shapes = ["orderbook", "time_series", "bars"]
        if subtype in {"large_trades", "whale_orders"}:
            shapes.append("event_list")
        return [(shape, f"{shape}.json") for shape in shapes]

    @staticmethod
    def _prices_variants(block: dict[str, Any]) -> list[tuple[str, str]]:
        if block.get("detected", {}).get("data_type") != "candlestick":
            return []
        return [
            ("candlestick", "candlestick.json"),
            ("time_series", "time_series.json"),
        ]

    @staticmethod
    def _volume_derivative_variants(block: dict[str, Any]) -> list[tuple[str, str]]:
        if block.get("detected", {}).get("data_type") != "candlestick":
            return []
        normalized = block.get("normalized", {})
        dataframe = normalized.get("dataframe")
        if not isinstance(dataframe, pd.DataFrame):
            return []
        if "volume" not in dataframe.columns and "notional_volume" not in dataframe.columns:
            return []
        return [("volume_features", "volume_features.json")]

    @staticmethod
    def _volume_orderflow_variants(block: dict[str, Any]) -> list[tuple[str, str]]:
        if block.get("detected", {}).get("data_type") != "cvd":
            return []
        return [
            ("cvd_time_series", "cvd_time_series.json"),
            ("cvd_candlestick_derived", "cvd_candlestick_derived.json"),
            ("orderflow_features", "orderflow_features.json"),
        ]

    @staticmethod
    def _four_shape_variants() -> list[tuple[str, str]]:
        return [
            ("time_series", "time_series.json"),
            ("bars", "bars.json"),
            ("event_list", "event_list.json"),
            ("candlestick_derived", "candlestick_derived.json"),
        ]

    @staticmethod
    def _open_interest_variants() -> list[tuple[str, str]]:
        return [
            ("time_series", "time_series.json"),
            ("candlestick_derived", "candlestick_derived.json"),
            ("regimes", "regimes.json"),
        ]

    @staticmethod
    def _sentiment_variants() -> list[tuple[str, str]]:
        return [
            ("time_series", "time_series.json"),
            ("bars", "bars.json"),
            ("candlestick_derived", "candlestick_derived.json"),
        ]

    @staticmethod
    def _network_onchain_variants() -> list[tuple[str, str]]:
        return [
            ("time_series", "time_series.json"),
            ("bars", "bars.json"),
            ("event_list", "event_list.json"),
            ("regimes", "regimes.json"),
        ]

    @staticmethod
    def _single_shape_variant(block: dict[str, Any]) -> list[tuple[str, str]]:
        output_shape = str(block.get("output_shape") or "time_series")
        output_filename = str(block.get("output_filename") or f"{output_shape}.json")
        return [(output_shape, output_filename)]

    @classmethod
    def _validate_family_output_limits(cls, grouped: dict[tuple[str, str], list[dict[str, Any]]]) -> None:
        counts: dict[str, set[str]] = defaultdict(set)
        for family_key, output_shape in grouped:
            counts[family_key].add(output_shape)

        too_many = {
            family_key: sorted(output_shapes)
            for family_key, output_shapes in counts.items()
            if family_key in cls.OFFICIAL_FAMILIES and len(output_shapes) > 4
        }
        if too_many:
            details = "; ".join(f"{family}: {shapes}" for family, shapes in sorted(too_many.items()))
            raise ValueError(f"Family output contract violation: more than 4 outputs generated for {details}")

    @staticmethod
    def _write_json(payload: dict[str, Any], output_path: Path) -> None:
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)

    def _to_json_safe(self, value: Any) -> Any:
        if isinstance(value, pd.DataFrame):
            return value.to_dict(orient="records")

        if isinstance(value, pd.Series):
            return value.to_list()

        if isinstance(value, dict):
            return {str(k): self._to_json_safe(v) for k, v in value.items()}

        if isinstance(value, list):
            return [self._to_json_safe(v) for v in value]

        return value

    @staticmethod
    def _unique_values(blocks: list[dict[str, Any]], key: str) -> list[Any]:
        values = []
        for block in blocks:
            value = block.get("detected", {}).get(key) if isinstance(block.get("detected"), dict) else None
            if value is None:
                value = block.get(key)
            if value is not None and value not in values:
                values.append(value)
        return values

    @staticmethod
    def _count_data_types(blocks: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for block in blocks:
            data_type = (
                block.get("detected", {}).get("data_type")
                if isinstance(block.get("detected"), dict)
                else block.get("data_type")
            )
            data_type = data_type or "unknown"
            counts[data_type] = counts.get(data_type, 0) + 1
        return counts

    @staticmethod
    def _build_ml_feature_matrix_preview(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for block in blocks:
            routes = block.get("routes", {})
            if not routes.get("ml", {}).get("include_feature_vector"):
                continue

            feature_snapshot = block.get("math", {}).get("feature_snapshot", {})
            row = {
                "source_name": block.get("source_name"),
                "data_type": block.get("detected", {}).get("data_type"),
                "symbol": block.get("detected", {}).get("symbol"),
                "timeframe": block.get("detected", {}).get("timeframe"),
            }
            row.update(feature_snapshot)
            rows.append(row)
        return rows

    @staticmethod
    def _build_statistical_regimes_summary(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for block in blocks:
            regimes = block.get("math", {}).get("statistical_regimes", {})
            if not regimes:
                continue
            rows.append(
                {
                    "source_name": block.get("source_name"),
                    "data_type": block.get("detected", {}).get("data_type"),
                    "symbol": block.get("detected", {}).get("symbol"),
                    "timeframe": block.get("detected", {}).get("timeframe"),
                    "numeric_columns": regimes.get("numeric_columns", []),
                    "windows": regimes.get("windows", []),
                    "last": regimes.get("last", {}),
                    "last_regimes": regimes.get("last_regimes", {}),
                }
            )
        return rows
