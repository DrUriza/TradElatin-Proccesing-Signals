from __future__ import annotations

from ..exporters import build_family_chart_payload
from ..models import FamilyChartPayload, FamilyProcessingPayload
from ..routing_rules import get_rule_for_family


FAMILY_KEY = "prices_ohlcv"


def classify(payload_by_shape: dict[str, FamilyProcessingPayload]) -> FamilyChartPayload:
    rule = get_rule_for_family(FAMILY_KEY)
    if rule is None:
        raise ValueError(f"Routing rule missing for family {FAMILY_KEY}")
    return build_family_chart_payload(rule=rule, family_payload_by_shape=payload_by_shape)
