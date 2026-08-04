from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy            import deepcopy
from numbers         import Integral, Real
from typing          import Any


LOW_VOL_PERCENTILE_THRESHOLD  = 1.0 / 3.0
HIGH_VOL_PERCENTILE_THRESHOLD = 2.0 / 3.0
CONFIDENCE_HIGH_THRESHOLD     = 0.75
CONFIDENCE_MEDIUM_THRESHOLD   = 0.40
POSITIONING_SHORT_THRESHOLD   = 0.95
POSITIONING_LONG_THRESHOLD    = 1.05
POSITIONING_EXTREME_SHORT     = 0.67
POSITIONING_EXTREME_LONG      = 1.50
DAY_SECONDS                   = 86400

REGIME_STATES       = {"low_vol", "normal", "high_vol"}
AVAILABILITY_STATES = {"available", "partial", "unavailable", "invalid"}
_MODES              = {"bootstrap", "incremental", "recovery"}
_AGREEMENT_FACTORS  = {
    "confirmed": 1.0, "implied_higher": 0.75, "implied_lower": 0.75,
    "implied_leads_higher": 0.75, "implied_leads_lower": 0.75,
    "divergent": 0.5, "unavailable": 0.65,
}
_BASIS_FIELDS = (
    "realized_volatility_percent", "implied_volatility_percent", "spread_volatility_points",
    "realized_z_score_30d", "implied_z_score_30d", "spread_z_score_30d",
    "realized_percentile_rank_90d", "implied_percentile_rank_90d", "spread_percentile_rank_90d",
    "long_short_ratio", "net_long_percentage_points",
)


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    result = float(value)
    return 0.0 if result == 0 else result


def _finite(value: Any, path: str, nullable: bool = True) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{path}:finite_number_required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path}:finite_number_required")
    return _clean(result)


def _timestamp(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{path}:integer_timestamp_required")
    return int(value)


def validate_volatility_market_regimes_processing_contract(contract: Any) -> None:
    if not isinstance(contract, Mapping):
        raise ValueError("processing_contract:mapping_required")
    if contract.get("family") != "volatility_market_regimes":
        raise ValueError("family:volatility_market_regimes_required")
    if contract.get("stage") != "processing":
        raise ValueError("stage:processing_required")
    if contract.get("version") != "0.1.0":
        raise ValueError("version:0.1.0_required")
    if contract.get("mode") not in _MODES:
        raise ValueError("mode:invalid")
    if not isinstance(contract.get("context"), Mapping):
        raise ValueError("context:mapping_required")
    if not isinstance(contract.get("features"), Mapping):
        raise ValueError("features:mapping_required")
    if not isinstance(contract.get("quality"), Mapping) or contract["quality"].get("status") not in {"ok", "partial", "invalid"}:
        raise ValueError("quality:invalid")
    for name in ("positioning", "volatility_comparison", "spread_metrics", "daily_regime_basis"):
        feature = contract["features"].get(name)
        if not isinstance(feature, Mapping) or feature.get("status") not in AVAILABILITY_STATES:
            raise ValueError(f"features.{name}:invalid")
    for feature_name in ("positioning", "daily_regime_basis"):
        records = contract["features"][feature_name].get("records")
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise ValueError(f"features.{feature_name}.records:sequence_required")
        seen = set()
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise ValueError(f"features.{feature_name}.records[{index}]:mapping_required")
            timestamp = _timestamp(record.get("timestamp"), f"features.{feature_name}.records[{index}].timestamp")
            if timestamp in seen:
                raise ValueError(f"features.{feature_name}.records:duplicate_timestamp")
            seen.add(timestamp)


def classify_percentile_regime(rank: Any) -> str | None:
    if rank is None:
        return None
    value = _finite(rank, "percentile_rank", nullable=False)
    if value < 0 or value > 1:
        raise ValueError("invalid_percentile_rank")
    if value < LOW_VOL_PERCENTILE_THRESHOLD:
        return "low_vol"
    if value > HIGH_VOL_PERCENTILE_THRESHOLD:
        return "high_vol"
    return "normal"


def classify_regime_agreement(realized_state: str | None, implied_state: str | None) -> str:
    if implied_state is None:
        return "unavailable"
    if realized_state == implied_state:
        return "confirmed"
    mapping = {
        ("low_vol", "normal"): "implied_higher", ("high_vol", "normal"): "implied_lower",
        ("normal", "high_vol"): "implied_leads_higher", ("normal", "low_vol"): "implied_leads_lower",
    }
    return mapping.get((realized_state, implied_state), "divergent")


def calculate_regime_confidence(realized_rank: Any, realized_state: str, agreement_state: str) -> dict[str, Any]:
    rank = _finite(realized_rank, "realized_percentile_rank_90d", nullable=False)
    if rank < 0 or rank > 1:
        raise ValueError("invalid_percentile_rank")
    if realized_state == "low_vol":
        strength = (LOW_VOL_PERCENTILE_THRESHOLD - rank) / LOW_VOL_PERCENTILE_THRESHOLD
    elif realized_state == "normal":
        strength = 1.0 - abs(rank - 0.5) / (HIGH_VOL_PERCENTILE_THRESHOLD - 0.5)
    elif realized_state == "high_vol":
        strength = (rank - HIGH_VOL_PERCENTILE_THRESHOLD) / (1.0 - HIGH_VOL_PERCENTILE_THRESHOLD)
    else:
        raise ValueError("realized_state:invalid")
    strength = _clean(min(max(strength, 0.0), 1.0))
    factor   = _AGREEMENT_FACTORS[agreement_state]
    score    = _clean(min(max(strength * factor, 0.0), 1.0))
    state    = "high" if score >= CONFIDENCE_HIGH_THRESHOLD else "medium" if score >= CONFIDENCE_MEDIUM_THRESHOLD else "low"
    return {
        "confidence_score": score, "confidence_state": state,
        "confidence_basis": "realized_percentile_boundary_distance_with_implied_agreement_factor",
        "realized_strength": strength, "agreement_factor": factor,
    }


def classify_daily_regime_record(record: Mapping[str, Any]) -> dict[str, Any]:
    timestamp = _timestamp(record.get("timestamp"), "daily_record.timestamp")
    basis     = {field: deepcopy(record.get(field)) for field in _BASIS_FIELDS}
    warnings  = []
    output    = {
        "timestamp": timestamp, "data_as_of": record.get("data_as_of"), "regime": None,
        "realized_state": None, "implied_state": None, "agreement_state": "unavailable",
        "confidence_score": None, "confidence_state": None, "confidence_basis": None,
        "realized_strength": None, "agreement_factor": None, "persistence_days": None,
        "basis": basis, "status": "unavailable", "reason": "realized_percentile_unavailable", "warnings": warnings,
    }
    if record.get("status") == "invalid":
        output.update(status="invalid", reason="invalid_processing_basis")
        return output
    realized_rank = record.get("realized_percentile_rank_90d")
    implied_rank  = record.get("implied_percentile_rank_90d")
    try:
        realized_state = classify_percentile_regime(realized_rank)
        implied_state  = classify_percentile_regime(implied_rank)
    except ValueError:
        output.update(status="invalid", reason="invalid_percentile_rank")
        return output
    if realized_state is None:
        return output
    agreement  = classify_regime_agreement(realized_state, implied_state)
    confidence = calculate_regime_confidence(realized_rank, realized_state, agreement)
    if implied_state is None:
        status, reason = "partial", "implied_confirmation_unavailable"
    elif record.get("long_short_ratio") is None:
        status, reason = "partial", "positioning_context_unavailable"
    else:
        status, reason = "available", None
    if record.get("long_short_ratio") is None and reason != "positioning_context_unavailable":
        warnings.append("positioning_context_unavailable")
    output.update({
        "regime": realized_state, "realized_state": realized_state, "implied_state": implied_state,
        "agreement_state": agreement, "status": status, "reason": reason, **confidence,
    })
    return output


def calculate_regime_persistence(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous_regime = None
    previous_time   = None
    persistence     = 0
    for record in records:
        valid = record.get("regime") in REGIME_STATES and record.get("status") in {"available", "partial"}
        if valid:
            consecutive = previous_regime == record["regime"] and previous_time is not None and record["timestamp"] - previous_time == DAY_SECONDS
            persistence = persistence + 1 if consecutive else 1
            record["persistence_days"] = persistence
            previous_regime = record["regime"]
            previous_time   = record["timestamp"]
        else:
            persistence, previous_regime, previous_time = 0, None, None
            record["persistence_days"] = None
    return records


def classify_daily_regime_history(feature: Mapping[str, Any]) -> dict[str, Any]:
    records = [classify_daily_regime_record(record) for record in sorted(feature.get("records", []), key=lambda item: item["timestamp"])]
    calculate_regime_persistence(records)
    current = next((deepcopy(record) for record in reversed(records) if record["regime"] is not None and record["status"] in {"available", "partial"}), None)
    if any(record["status"] == "invalid" for record in records):
        status, reason = "invalid", "invalid_daily_regime_record"
    elif not current:
        status, reason = "unavailable", "current_regime_unavailable"
    elif any(record["status"] != "available" for record in records) or feature.get("status") != "available":
        status, reason = "partial", "daily_regime_history_partial"
    else:
        status, reason = "available", None
    return {
        "status": status, "reason": reason, "records": records, "current": current,
        "current_persistence_days": current["persistence_days"] if current else None,
        "records_available": len(records), "source_data_as_of": feature.get("source_data_as_of"),
    }


def _distribution(records: Sequence[Mapping[str, Any]], window: str) -> dict[str, Any]:
    valid = [record for record in records if record.get("regime") in REGIME_STATES and record.get("status") in {"available", "partial"}]
    if window == "30d" and valid:
        end   = valid[-1]["timestamp"]
        start = end - 29 * DAY_SECONDS
        valid = [record for record in valid if start <= record["timestamp"] <= end]
    if not valid:
        return {
            "status": "unavailable", "reason": "no_classified_regime_days", "basis": "empirical_classified_day_share", "window": window,
            "window_start_timestamp": None, "window_end_timestamp": None, "classified_days": 0,
            "counts": {state: 0 for state in ("low_vol", "normal", "high_vol")},
            "shares": {state: None for state in ("low_vol", "normal", "high_vol")},
        }
    counts = {state: sum(record["regime"] == state for record in valid) for state in ("low_vol", "normal", "high_vol")}
    total  = len(valid)
    return {
        "status": "available", "reason": None, "basis": "empirical_classified_day_share", "window": window,
        "window_start_timestamp": valid[0]["timestamp"], "window_end_timestamp": valid[-1]["timestamp"], "classified_days": total,
        "counts": counts, "shares": {state: _clean(counts[state] / total) for state in counts},
    }


def calculate_regime_distribution(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {"full_history": _distribution(records, "full_history"), "trailing_30d": _distribution(records, "30d")}


def calculate_regime_statistics(records: Sequence[Mapping[str, Any]], current: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
    valid = [record for record in records if record.get("regime") in REGIME_STATES and record.get("status") in {"available", "partial"}]
    episodes: list[tuple[str, int]] = []
    for record in valid:
        if episodes and episodes[-1][0] == record["regime"] and record["persistence_days"] > 1:
            episodes[-1] = (episodes[-1][0], episodes[-1][1] + 1)
        else:
            episodes.append((record["regime"], 1))
    total         = len(valid)
    current_state = current.get("regime") if current else None
    output        = []
    for state in ("low_vol", "normal", "high_vol"):
        lengths = [length for regime, length in episodes if regime == state]
        days    = sum(record["regime"] == state for record in valid)
        active  = current_state == state
        output.append({
            "regime": state, "classified_days": days, "empirical_share": _clean(days / total) if total else None,
            "episode_count": len(lengths), "average_episode_days": _clean(sum(lengths) / len(lengths)) if lengths else None,
            "maximum_episode_days": max(lengths) if lengths else None,
            "current_episode_days": current.get("persistence_days", 0) if active else 0, "is_current": active,
        })
    return output


def build_regime_transition_events(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id    = {}
    ids      = []
    previous = None
    rank     = {"low_vol": 0, "normal": 1, "high_vol": 2}
    for record in records:
        valid = record.get("regime") in REGIME_STATES and record.get("status") in {"available", "partial"}
        if valid and previous and record["timestamp"] - previous["timestamp"] == DAY_SECONDS and record["regime"] != previous["regime"]:
            event_id = f"volatility_market_regimes:{record['timestamp']}:regime_transition:{previous['regime']}:{record['regime']}"
            by_id[event_id] = {
                "event_id": event_id, "event_type": "regime_transition", "timestamp": record["timestamp"],
                "from_regime": previous["regime"], "to_regime": record["regime"],
                "transition_direction": "volatility_expansion" if rank[record["regime"]] > rank[previous["regime"]] else "volatility_contraction",
                "confidence_score": record.get("confidence_score"), "data_as_of": record.get("data_as_of"),
            }
            ids.append(event_id)
        previous = record if valid else None
    return {"by_id": by_id, "regime_transition_ids": ids}


def classify_positioning_record(record: Mapping[str, Any]) -> dict[str, Any]:
    ratio    = _finite(record.get("long_short_ratio"), "long_short_ratio", nullable=False)
    state    = "short_bias" if ratio < POSITIONING_SHORT_THRESHOLD else "long_bias" if ratio > POSITIONING_LONG_THRESHOLD else "balanced"
    crowding = "extreme_short" if ratio <= POSITIONING_EXTREME_SHORT else "extreme_long" if ratio >= POSITIONING_EXTREME_LONG else "normal"
    return {
        "timestamp": _timestamp(record.get("timestamp"), "positioning.timestamp"),
        "long_percent": _finite(record.get("long_percent"), "long_percent", nullable=False),
        "short_percent": _finite(record.get("short_percent"), "short_percent", nullable=False),
        "long_short_ratio": ratio, "net_long_percentage_points": _finite(record.get("net_long_percentage_points"), "net_long_percentage_points", nullable=False),
        "positioning_state": state, "crowding_state": crowding, "status": "available", "reason": None,
    }


def classify_positioning_history(feature: Mapping[str, Any]) -> dict[str, Any]:
    if feature.get("status") in {"unavailable", "invalid"} and not feature.get("records"):
        status = "invalid" if feature.get("status") == "invalid" else "unavailable"
        reason = "invalid_positioning_feature" if status == "invalid" else "positioning_feature_unavailable"
        return {"status": status, "reason": reason, "records": [], "current": None, "records_available": 0, "source_data_as_of": feature.get("source_data_as_of")}
    records = []
    for raw in sorted(feature.get("records", []), key=lambda item: item["timestamp"]):
        try:
            records.append(classify_positioning_record(raw))
        except (TypeError, ValueError):
            records.append({"timestamp": raw.get("timestamp"), "status": "invalid", "reason": "invalid_positioning_record"})
    valid = [record for record in records if record["status"] == "available"]
    if any(record["status"] == "invalid" for record in records):
        status, reason = "invalid", "invalid_positioning_record"
    elif feature.get("status") == "available" and valid:
        status, reason = "available", None
    elif valid:
        status, reason = "partial", feature.get("reason") or "positioning_feature_partial"
    else:
        status, reason = "unavailable", "positioning_feature_unavailable"
    return {"status": status, "reason": reason, "records": records, "current": deepcopy(valid[-1]) if valid else None,
            "records_available": len(valid), "source_data_as_of": feature.get("source_data_as_of")}


def classify_spread_context(feature: Mapping[str, Any]) -> dict[str, Any]:
    value  = _finite(feature.get("value"), "spread_metrics.value")
    state  = "unavailable" if value is None else "realized_below_implied" if value < 0 else "realized_above_implied" if value > 0 else "balanced"
    fields = ("status", "reason", "unit", "basis", "window", "records_used", "coverage", "window_start_timestamp", "window_end_timestamp")
    output = {field: deepcopy(feature.get(field)) for field in fields}
    output.update(value=value, spread_state=state)
    if output["status"] != "available" and not output["reason"]:
        output["reason"] = "spread_context_unavailable" if value is None else "spread_context_partial"
    return output


def _source_availability(features: Mapping[str, Any]) -> dict[str, Any]:
    output = {}
    for name in ("positioning", "volatility_comparison", "spread_metrics", "daily_regime_basis"):
        feature = features[name]
        output[f"processing.{name}"] = {
            "status": feature.get("status"), "reason": feature.get("reason"),
            "records_available": feature.get("records_available"), "source_data_as_of": feature.get("source_data_as_of"),
        }
    return output


def evaluate_volatility_market_regimes_classification_quality(
    classifications: Mapping[str, Any], distribution: Mapping[str, Any], events: Mapping[str, Any], processing_status: str, errors: Sequence[str] = (), warnings: Sequence[str] = (),
) -> dict[str, Any]:
    required     = ["daily_regimes", "positioning", "spread_context"]
    groups       = {state: [name for name in required if classifications[name].get("status") == state] for state in AVAILABILITY_STATES}
    current      = classifications["daily_regimes"].get("current")
    refs_ok      = all(event_id in events["by_id"] for event_id in events["regime_transition_ids"])
    all_warnings = sorted(set(warnings))
    if errors or groups["invalid"] or processing_status == "invalid" or not refs_ok:
        status = "invalid"
    elif processing_status != "ok" or groups["partial"] or groups["unavailable"] or not current or all_warnings:
        status = "partial"
    else:
        status = "ok"
    return {
        "status": status, "required_classifications": required, "available_classifications": groups["available"],
        "partial_classifications": groups["partial"], "unavailable_classifications": groups["unavailable"], "invalid_classifications": groups["invalid"],
        "current_regime_available": current is not None, "confidence_available": bool(current and current.get("confidence_score") is not None),
        "persistence_available": bool(current and current.get("persistence_days") is not None),
        "distribution_available": distribution["full_history"]["status"] == "available", "events_complete": refs_ok,
        "warnings": all_warnings, "errors": list(errors),
    }


def _context(processing: Mapping[str, Any]) -> dict[str, Any]:
    source = processing.get("context") if isinstance(processing.get("context"), Mapping) else {}
    return {
        "reference_timestamp": source.get("reference_timestamp"), "input_execution_timestamp": source.get("input_execution_timestamp"),
        "asset": source.get("asset"), "symbol": source.get("symbol"), "exchange": source.get("exchange"), "base_interval": source.get("base_interval"),
        "parameters": {
            "low_vol_percentile_threshold": LOW_VOL_PERCENTILE_THRESHOLD, "high_vol_percentile_threshold": HIGH_VOL_PERCENTILE_THRESHOLD,
            "confidence_high_threshold": CONFIDENCE_HIGH_THRESHOLD, "confidence_medium_threshold": CONFIDENCE_MEDIUM_THRESHOLD,
            "positioning_short_threshold": POSITIONING_SHORT_THRESHOLD, "positioning_long_threshold": POSITIONING_LONG_THRESHOLD,
            "positioning_extreme_short": POSITIONING_EXTREME_SHORT, "positioning_extreme_long": POSITIONING_EXTREME_LONG,
        },
        "classification_policy": {
            "primary_regime_basis": "realized_percentile_rank_90d", "confirmation_basis": "implied_percentile_rank_90d",
            "confidence_basis": "realized_percentile_boundary_distance_with_implied_agreement_factor",
            "distribution_basis": "empirical_classified_day_share", "persistence_basis": "consecutive_classified_utc_days",
        },
        "history_policy": {"calculation": "full_processing_history", "presentation": "not_applied_in_classification"},
    }


def _invalid_contract(processing: Any, error: str) -> dict[str, Any]:
    safe            = processing if isinstance(processing, Mapping) else {}
    invalid         = {"status": "invalid", "reason": "processing_contract_invalid", "records": [], "current": None}
    classifications = {"daily_regimes": deepcopy(invalid), "positioning": deepcopy(invalid),
                       "spread_context": {"status": "invalid", "reason": "processing_contract_invalid", "value": None, "spread_state": "unavailable"}}
    distribution = calculate_regime_distribution([])
    events       = {"by_id": {}, "regime_transition_ids": []}
    quality      = evaluate_volatility_market_regimes_classification_quality(classifications, distribution, events, "invalid", [error])
    return {
        "family": "volatility_market_regimes", "stage": "classification", "version": "0.1.0",
        "mode": safe.get("mode") if safe.get("mode") in _MODES else "bootstrap", "context": _context(safe), "source_availability": {},
        "classifications": classifications, "summaries": {"regime_distribution": distribution, "regime_statistics": calculate_regime_statistics([])},
        "interpreted_events": events, "quality": quality,
    }


class VolatilityMarketRegimesClassifier:
    def classify(self, processing: Any) -> dict[str, Any]:
        try:
            validate_volatility_market_regimes_processing_contract(processing)
            features        = processing["features"]
            daily           = classify_daily_regime_history(features["daily_regime_basis"])
            positioning     = classify_positioning_history(features["positioning"])
            spread          = classify_spread_context(features["spread_metrics"])
            classifications = {"daily_regimes": daily, "positioning": positioning, "spread_context": spread}
            distribution    = calculate_regime_distribution(daily["records"])
            statistics      = calculate_regime_statistics(daily["records"], daily["current"])
            events          = build_regime_transition_events(daily["records"])
            warnings        = [warning for record in daily["records"] for warning in record.get("warnings", [])]
            quality         = evaluate_volatility_market_regimes_classification_quality(
                classifications, distribution, events, processing["quality"]["status"], warnings=warnings,
            )
            return {
                "family": "volatility_market_regimes", "stage": "classification", "version": "0.1.0", "mode": processing["mode"],
                "context": _context(processing), "source_availability": _source_availability(features), "classifications": classifications,
                "summaries": {"regime_distribution": distribution, "regime_statistics": statistics}, "interpreted_events": events, "quality": quality,
            }
        except (KeyError, TypeError, ValueError) as exc:
            return _invalid_contract(processing, str(exc))


def classify_volatility_market_regimes(processing: Any) -> dict[str, Any]:
    return VolatilityMarketRegimesClassifier().classify(processing)
