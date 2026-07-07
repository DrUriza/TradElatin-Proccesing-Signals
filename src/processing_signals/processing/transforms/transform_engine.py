from __future__ import annotations

from typing import Any

import pandas as pd

from processing_signals.processing.transforms.candlestick_to_time_series import candlestick_to_time_series
from processing_signals.processing.transforms.event_extractor import extract_events
from processing_signals.processing.transforms.orderbook_to_bars import orderbook_to_bars
from processing_signals.processing.transforms.time_series_to_bars import EXCLUDED_REFERENCE_COLUMNS, time_series_to_bars
from processing_signals.processing.transforms.time_series_to_candlestick import time_series_to_candlestick


class TransformEngine:
    """Prepare reusable view transforms before math/output layers."""

    def transform_blocks(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.transform_block(block) for block in blocks]

    def transform_block(self, block: dict[str, Any]) -> dict[str, Any]:
        block["transforms"] = self.transform(
            block["normalized"],
            block["detected"],
        )
        return block

    def transform(
        self,
        normalized: dict[str, Any],
        detected: dict[str, Any],
    ) -> dict[str, Any]:
        views: dict[str, Any] = {}
        classification = detected.get("classification_input", {})
        if not isinstance(classification, dict):
            classification = {}
        structural_data_type = classification.get("structural_data_type")
        required_views = set(classification.get("required_views") or [])
        dataframe = normalized.get("dataframe")

        if structural_data_type in {"snapshot", "matrix", "heatmap"}:
            if structural_data_type not in required_views:
                return {}
            return {
                structural_data_type: {
                    "records": dataframe if not isinstance(dataframe, pd.DataFrame) else dataframe.to_dict(orient="records")
                }
            }

        if isinstance(dataframe, pd.DataFrame):
            numeric_columns = numeric_columns_from(dataframe)
            bars: list[dict[str, Any]] = []
            reference: str | None = None
            warning: str | None = None
            if "bars" in required_views or "candlestick_derived" in required_views:
                if normalized.get("kind") == "orderbook_conventional":
                    bars, reference, warning = orderbook_to_bars(dataframe)
                else:
                    bars, reference, warning = time_series_to_bars(
                        dataframe,
                        preferred=None,
                        semantic_subtype=classification.get("semantic_subtype"),
                        family=classification.get("official_family"),
                    )
            if "bars" in required_views:
                views["bars"] = {"records": bars, "reference_column": reference}
                if warning:
                    views["bars"]["warning"] = warning
            if "candlestick_derived" in required_views:
                candles, conversion = time_series_to_candlestick(
                    dataframe,
                    preferred_reference=reference,
                    semantic_subtype=classification.get("semantic_subtype"),
                    family=classification.get("official_family"),
                )
                views["candlestick_derived"] = {"records": candles, "conversion": conversion}
            if "time_series" in required_views:
                views["time_series"] = candlestick_to_time_series(dataframe) if normalized.get("kind") == "candlestick" else dataframe
            if "event_list" in required_views:
                views["event_list"] = {
                    "events": extract_events(
                        dataframe,
                        numeric_columns,
                        detected.get("metadata", {}).get("family") or "",
                        detected.get("data_type"),
                        detected.get("source_name"),
                        detected.get("symbol"),
                        detected.get("timeframe"),
                    )
                }

        events = normalized.get("events")
        if isinstance(events, pd.DataFrame) and "event_list" in required_views:
            views["event_list"] = {"events": events}
        if normalized.get("kind") == "orderbook_conventional" and "depth" in required_views:
            views["depth"] = {
                "bids": normalized.get("bids"),
                "asks": normalized.get("asks"),
                "summary": normalized.get("summary", {}),
            }
        return views


def numeric_columns_from(frame: pd.DataFrame) -> list[str]:
    excluded = {
        "timestamp_utc",
        "family_key",
        "data_type",
        "source_subtype",
        "base_asset",
        "quote_asset",
    } | EXCLUDED_REFERENCE_COLUMNS
    return [
        str(column)
        for column in frame.select_dtypes(include="number").columns
        if str(column).lower() not in excluded
    ]
