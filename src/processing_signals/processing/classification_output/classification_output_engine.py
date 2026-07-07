from __future__ import annotations

from typing import Any


class ClassificationOutput:
    """Group processed blocks for downstream HMI consumption without visualization work."""

    def classify(self, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [self.classify_block(block) for block in blocks]

    def classify_block(self, block: dict[str, Any]) -> dict[str, Any]:
        classification_input = block.get("classification_input", {})
        if not isinstance(classification_input, dict):
            classification_input = {}

        fixed_window = classification_input.get("fixed_window") or classification_input.get("extraction_window")
        output = {
            "official_family": classification_input.get("official_family") or "unknown",
            "hmi_mode": classification_input.get("hmi_mode") or "timeframe_window",
            "primary_view_type": classification_input.get("primary_view_type") or "time_series",
            "timeframe": classification_input.get("timeframe"),
            "fixed_window": fixed_window,
            "extraction_window": fixed_window,
            "source_window_type": classification_input.get("source_window_type"),
            "record_window_type": classification_input.get("record_window_type"),
            "semantic_subtype": classification_input.get("semantic_subtype")
            or classification_input.get("subtype")
            or "unknown",
            "subtype": classification_input.get("semantic_subtype")
            or classification_input.get("subtype")
            or "unknown",
            "data_type": classification_input.get("data_type")
            or classification_input.get("semantic_subtype")
            or classification_input.get("subtype")
            or "unknown",
            "structural_data_type": classification_input.get("structural_data_type") or "time_series",
            "available_views": available_views(block.get("transforms", {}), block.get("normalized", {})),
            "math_outputs": non_empty_outputs(block.get("math", {}), block.get("view_math", {})),
            "pattern_outputs": non_empty_outputs(block.get("patterns", {})),
        }
        block["classification_output"] = output
        return block


def available_views(transforms: Any, normalized: Any) -> list[str]:
    views: set[str] = set()
    if isinstance(transforms, dict):
        for view_name, payload in transforms.items():
            if has_payload(payload):
                views.add(str(view_name))
    if isinstance(normalized, dict):
        kind = normalized.get("kind")
        if kind == "candlestick":
            views.add("candlestick")
        elif kind == "orderbook_conventional":
            views.add("depth")
        elif kind in {"orderbook_large_trades", "orderbook_whale_orders"}:
            views.add("event_list")
    return sorted(views)


def non_empty_outputs(*payloads: Any) -> list[str]:
    outputs: set[str] = set()
    for payload in payloads:
        if not isinstance(payload, dict):
            continue
        for key, value in payload.items():
            if has_payload(value):
                outputs.add(str(key))
    return sorted(outputs)


def has_payload(value: Any) -> bool:
    if value is None:
        return False
    if hasattr(value, "empty"):
        return not bool(value.empty)
    if isinstance(value, dict):
        return any(has_payload(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return len(value) > 0
    return True
