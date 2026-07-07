from __future__ import annotations

from typing import Any

import pandas as pd


class ProcessingNormalization:
    """Normalize Classification Input blocks without running transforms or math."""

    def normalize(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.normalize_classified_block(block) for block in blocks]

    def normalize_classified_block(self, block: dict[str, Any]) -> dict[str, Any]:
        block["normalized"] = self._normalize_payload(block["raw_payload"], block["detected"])
        block.pop("raw_payload", None)
        return block

    def _normalize_payload(self, payload: dict[str, Any], detected: dict[str, Any]) -> dict[str, Any]:
        classification = detected.get("classification_input", {})
        if not isinstance(classification, dict):
            classification = {}
        structural = classification.get("structural_data_type") or "time_series"
        semantic = classification.get("semantic_subtype") or detected.get("data_type") or "unknown"

        if structural == "orderbook":
            return self._normalize_orderbook(payload, semantic)
        if semantic in {"orderbook_large_trades", "orderbook_whale_orders"}:
            return self._normalize_events(payload, semantic)
        if structural == "event_list":
            return self._normalize_events(payload, semantic)

        frame = self._records_frame(payload)
        return {
            "kind": "candlestick" if structural == "candlestick" else str(semantic),
            "structural_data_type": structural,
            "semantic_subtype": semantic,
            "dataframe": frame,
            "records_count": len(frame),
            "metadata": detected.get("metadata", {}),
        }

    def _normalize_orderbook(self, payload: dict[str, Any], semantic: str) -> dict[str, Any]:
        bids = pd.DataFrame(payload.get("bids") or [])
        asks = pd.DataFrame(payload.get("asks") or [])
        records = self._records_frame(payload)
        return {
            "kind": "orderbook_conventional" if semantic == "orderbook_conventional" else semantic,
            "structural_data_type": "orderbook",
            "semantic_subtype": semantic,
            "dataframe": records,
            "bids": self._with_notional(bids),
            "asks": self._with_notional(asks),
            "summary": payload.get("summary", {}),
            "records_count": len(records) if not records.empty else len(bids) + len(asks),
        }

    def _normalize_events(self, payload: dict[str, Any], semantic: str) -> dict[str, Any]:
        candidates: list[dict[str, Any]] = []
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                candidates.extend(value)
        events = pd.DataFrame(candidates)
        if events.empty:
            events = self._records_frame(payload)
        return {
            "kind": semantic,
            "structural_data_type": "event_list",
            "semantic_subtype": semantic,
            "events": events,
            "records_count": len(events),
            "metadata": payload.get("metadata", {}),
        }

    @staticmethod
    def _records_frame(payload: dict[str, Any]) -> pd.DataFrame:
        records = payload.get("records")
        if isinstance(records, list):
            return expand_dict_columns(pd.DataFrame(records))
        return expand_dict_columns(pd.DataFrame([payload]))

    @staticmethod
    def _with_notional(frame: pd.DataFrame) -> pd.DataFrame:
        if frame.empty:
            return frame
        if "notional_usdt" not in frame.columns and {"price", "quantity_btc"}.issubset(frame.columns):
            frame = frame.copy()
            frame["notional_usdt"] = frame["price"] * frame["quantity_btc"]
        return frame


def expand_dict_columns(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    expanded = frame.copy()
    for column in list(frame.columns):
        dict_rows = frame[column].dropna()
        if dict_rows.empty or not dict_rows.map(lambda value: isinstance(value, dict)).any():
            continue
        normalized = pd.json_normalize(frame[column]).add_prefix(f"{column}_")
        expanded = pd.concat([expanded.drop(columns=[column]), normalized], axis=1)
    return expanded
