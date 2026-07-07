from __future__ import annotations

from typing import Any

from processing_signals.processing.classification_input.family_contract import official_family_from
from processing_signals.processing.classification_input.view_contract import (
    STRUCTURAL_DATA_TYPES,
    hmi_mode_for,
    primary_view_type_for,
    required_views_for,
)
from processing_signals.processing.extraction import ProcessingInputRecord


class ClassificationInput:
    """Classify extracted Input payloads before transforms, math, and patterns."""

    def classify(self, records: list[ProcessingInputRecord]) -> list[dict[str, Any]]:
        return [self.classify_record(record) for record in records]

    def classify_record(self, record: ProcessingInputRecord) -> dict[str, Any]:
        detected = self._detect(record.payload, source_name=record.source_name)
        metadata = detected.get("metadata", {}) if isinstance(detected.get("metadata"), dict) else {}
        decision = self._decision(record.payload, detected, metadata)
        detected["classification_input"] = decision
        detected["metadata"] = {
            **metadata,
            "official_family": decision["official_family"],
            "semantic_subtype": decision["semantic_subtype"],
            "structural_data_type": decision["structural_data_type"],
            "fixed_window": decision["fixed_window"],
        }
        return {
            "source_name": record.source_name,
            "raw_payload": record.payload,
            "detected": detected,
            "classification_input": decision,
            "decision": decision,
        }

    def _detect(self, payload: dict[str, Any], source_name: str) -> dict[str, Any]:
        metadata = payload.get("metadata", {}) if isinstance(payload.get("metadata"), dict) else {}
        data_type = self._first_string(
            payload.get("subtype"),
            metadata.get("semantic_subtype"),
            metadata.get("subtype"),
            payload.get("data_type"),
            metadata.get("data_type"),
            "unknown",
        )
        structural = self._first_string(
            payload.get("data_type"),
            metadata.get("structural_data_type"),
            metadata.get("input_data_type"),
            "time_series",
        )
        canonical_type = {
            "candlestick": "ohlcv",
            "orderbook": "book_snapshot",
            "event_list": "event_list",
            "snapshot": "snapshot",
            "matrix": "matrix",
            "heatmap": "heatmap",
        }.get(structural, "time_series")
        return {
            "source_name": source_name,
            "data_type": data_type,
            "canonical_type": canonical_type,
            "confidence": "high",
            "symbol": metadata.get("symbol") or payload.get("symbol"),
            "timeframe": metadata.get("timeframe") or payload.get("timeframe"),
            "asset": metadata.get("asset") or payload.get("asset"),
            "provider_source": metadata.get("source") or payload.get("provider"),
            "timestamp_utc": metadata.get("timestamp_utc") or metadata.get("created_at_utc"),
            "metadata": metadata,
            "suggested_family_key": metadata.get("family") or payload.get("family"),
        }

    def _decision(
        self,
        payload: dict[str, Any],
        detected: dict[str, Any],
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        official_family = official_family_from(payload, metadata)
        provider = self._first_string(payload.get("provider"), metadata.get("provider"), metadata.get("source"), "unknown")
        semantic_subtype = self._first_string(
            payload.get("subtype"),
            metadata.get("semantic_subtype"),
            metadata.get("subtype"),
            detected.get("data_type"),
            "unknown",
        )
        structural_data_type = self._structural_data_type(payload, detected, metadata, semantic_subtype)
        timeframe = self._optional_string(payload.get("timeframe"), metadata.get("timeframe"), detected.get("timeframe"))
        fixed_window = self._optional_string(payload.get("fixed_window"), payload.get("extraction_window"), metadata.get("extraction_window"))
        hmi_mode = hmi_mode_for(official_family)
        primary_view_type = primary_view_type_for(structural_data_type)
        source_window_type = source_window_type_for(timeframe, fixed_window)

        return {
            "official_family": official_family,
            "provider": provider,
            "subtype": semantic_subtype,
            "data_type": semantic_subtype,
            "semantic_subtype": semantic_subtype,
            "structural_data_type": structural_data_type,
            "primary_view_type": primary_view_type,
            "timeframe": timeframe,
            "fixed_window": fixed_window,
            "extraction_window": fixed_window,
            "source_window_type": source_window_type,
            "record_window_type": source_window_type,
            "hmi_mode": hmi_mode,
            "required_views": required_views_for(
                official_family,
                semantic_subtype,
                structural_data_type,
                hmi_mode,
            ),
            "apply_technical_indicators": structural_data_type == "candlestick",
            "apply_microstructure_metrics": structural_data_type in {"orderbook", "event_list"},
            "apply_patterns": structural_data_type in {"time_series", "candlestick", "orderbook", "event_list"},
            "output_targets": {
                "hmi": True,
                "ml": True,
                "advanced_algorithms": True,
            },
            "targets": {
                "hmi": True,
                "ml": True,
                "advanced_algorithms": True,
            },
        }

    def _structural_data_type(
        self,
        payload: dict[str, Any],
        detected: dict[str, Any],
        metadata: dict[str, Any],
        semantic_subtype: str,
    ) -> str:
        declared = self._first_string(
            payload.get("data_type"),
            metadata.get("structural_data_type"),
            metadata.get("input_data_type"),
            metadata.get("data_type"),
            "",
        ).lower()
        canonical = str(detected.get("canonical_type") or "").lower()
        detected_type = str(detected.get("data_type") or "").lower()
        semantic = semantic_subtype.lower()

        if declared in STRUCTURAL_DATA_TYPES:
            if declared == "time_series" and "orderbook" in semantic:
                return "orderbook"
            return declared
        if canonical == "ohlcv" or detected_type == "candlestick":
            return "candlestick"
        if canonical in {"book_snapshot"} or "orderbook" in semantic or "orderbook" in detected_type:
            return "orderbook"
        if canonical in {"event_list", "event_list_with_ttl"}:
            return "event_list"
        if canonical == "metadata":
            return "snapshot"
        if "heatmap" in semantic or "heatmap" in detected_type:
            return "heatmap"
        if "matrix" in semantic or "matrix" in detected_type:
            return "matrix"
        if "snapshot" in semantic or "snapshot" in detected_type:
            return "snapshot"
        return "time_series"

    @staticmethod
    def _first_string(*values: Any) -> str:
        for value in values:
            if value is not None and str(value).strip():
                return str(value)
        return ""

    def _optional_string(self, *values: Any) -> str | None:
        value = self._first_string(*values)
        return value or None


def source_window_type_for(timeframe: str | None, fixed_window: str | None) -> str | None:
    if timeframe:
        return "timeframe"
    if fixed_window:
        return "fixed_window"
    return None
