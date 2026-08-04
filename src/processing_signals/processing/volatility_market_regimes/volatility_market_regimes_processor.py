from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from copy            import deepcopy
from numbers         import Integral, Real
from typing          import Any

from processing_signals.processing.math.statistics.descriptive_statistics import calculate_mean, calculate_standard_deviation

from .volatility_market_regimes_feature_builder import VolatilityMarketRegimesFeatureBuilder


BASE_INTERVAL_SECONDS           = 3600
DAY_SECONDS                     = 86400
SPREAD_WINDOW_HOURS             = 168
SPREAD_MIN_VALID_RECORDS        = 126
SPREAD_MIN_COVERAGE             = 0.75
ZSCORE_WINDOW_DAYS              = 30
ZSCORE_MIN_VALID_RECORDS        = 20
ZSCORE_DDOF                     = 1
PERCENTILE_WINDOW_DAYS          = 90
PERCENTILE_MIN_VALID_RECORDS    = 30
DAILY_AGGREGATION               = "last_valid_observation_utc_day"
PROCESSING_RECALCULATION_POLICY = "full_available_history"

_MODES    = {"bootstrap", "incremental", "recovery"}
_STATUSES = {"available", "partial", "unavailable", "invalid"}
_SOURCES  = (
    ("coinglass.top_position_ratio", "coinglass", "top_position_ratio"),
    ("glassnode.realized_volatility", "glassnode", "realized_volatility"),
    ("deribit.volatility_index", "deribit", "volatility_index"),
)


def _number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{path}:finite_number_required")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{path}:finite_number_required")
    return 0.0 if result == 0 else result


def _timestamp(value: Any, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise ValueError(f"{path}:integer_timestamp_required")
    return int(value)


def _dataset(contract: Mapping[str, Any], provider: str, dataset: str, path: str) -> Mapping[str, Any]:
    providers = contract["providers"]
    group     = providers.get(provider)
    if not isinstance(group, Mapping) or not isinstance(group.get(dataset), Mapping):
        raise ValueError(f"{path}:mapping_required")
    return group[dataset]


def validate_volatility_market_regimes_input(contract: Any) -> None:
    if not isinstance(contract, Mapping):
        raise ValueError("input:mapping_required")
    if contract.get("family") != "volatility_market_regimes":
        raise ValueError("family:volatility_market_regimes_required")
    if contract.get("stage") != "input_preprocessed":
        raise ValueError("stage:input_preprocessed_required")
    if contract.get("mode") not in _MODES:
        raise ValueError("mode:invalid")
    _timestamp(contract.get("reference_timestamp"), "reference_timestamp")
    _timestamp(contract.get("execution_timestamp"), "execution_timestamp")
    if not isinstance(contract.get("dimensions"), Mapping):
        raise ValueError("dimensions:mapping_required")
    if not isinstance(contract.get("providers"), Mapping):
        raise ValueError("providers:mapping_required")
    field_sets = {
        "coinglass.top_position_ratio": ("long_percent", "short_percent", "long_short_ratio"),
        "glassnode.realized_volatility": ("value_percent",),
        "deribit.volatility_index": ("open_percent", "high_percent", "low_percent", "close_percent"),
    }
    for key, provider, dataset_name in _SOURCES:
        dataset = _dataset(contract, provider, dataset_name, key)
        if dataset.get("status") not in _STATUSES:
            raise ValueError(f"{key}.status:invalid")
        records = dataset.get("records")
        if isinstance(records, (str, bytes)) or not isinstance(records, Sequence):
            raise ValueError(f"{key}.records:sequence_required")
        seen = set()
        for index, record in enumerate(records):
            path = f"{key}.records[{index}]"
            if not isinstance(record, Mapping):
                raise ValueError(f"{path}:mapping_required")
            timestamp = _timestamp(record.get("timestamp"), f"{path}.timestamp")
            if timestamp in seen:
                raise ValueError(f"{key}.records:duplicate_timestamp")
            seen.add(timestamp)
            for field in field_sets[key]:
                _number(record.get(field), f"{path}.{field}")


def extract_processing_source_records(contract: Mapping[str, Any]) -> dict[str, Any]:
    output = {}
    for key, provider, dataset_name in _SOURCES:
        dataset = _dataset(contract, provider, dataset_name, key)
        records = sorted((deepcopy(dict(record)) for record in dataset["records"]), key=lambda item: int(item["timestamp"]))
        output[key] = {"status": dataset["status"], "reason": dataset.get("reason"), "records": records}
    return output


def _history(records: list[dict[str, Any]]) -> dict[str, Any]:
    first = records[0]["timestamp"] if records else None
    last  = records[-1]["timestamp"] if records else None
    return {
        "records_available": len(records), "first_available_timestamp": first,
        "last_available_timestamp": last, "source_data_as_of": last,
    }


def build_positioning_series(source: Mapping[str, Any]) -> dict[str, Any]:
    records = []
    for raw in source["records"]:
        long_percent  = _number(raw["long_percent"], "long_percent")
        short_percent = _number(raw["short_percent"], "short_percent")
        records.append({
            "timestamp": _timestamp(raw["timestamp"], "timestamp"), "long_percent": long_percent,
            "short_percent": short_percent, "long_short_ratio": _number(raw["long_short_ratio"], "long_short_ratio"),
            "net_long_percentage_points": _clean(long_percent - short_percent),
        })
    records.sort(key=lambda item: item["timestamp"])
    if not records:
        status, reason = "unavailable", source.get("reason") or "positioning_records_unavailable"
    elif source["status"] == "available":
        status, reason = "available", None
    else:
        status, reason = "partial", source.get("reason") or "positioning_source_partial"
    return {
        "status": status, "reason": reason, "interval": "1h", "interval_seconds": BASE_INTERVAL_SECONDS,
        "unit": "ratio", "records": records, "current": deepcopy(records[-1]) if records else None,
        **_history(records),
        "source": {"provider": "coinglass", "endpoint_id": "top_position_long_short_ratio", "exchange": "Binance", "symbol": "BTCUSDT"},
    }


def _clean(value: float | None) -> float | None:
    if value is None:
        return None
    value = float(value)
    return 0.0 if value == 0 else value


def build_volatility_comparison_series(realized_source: Mapping[str, Any], implied_source: Mapping[str, Any]) -> dict[str, Any]:
    realized = {int(row["timestamp"]): _number(row["value_percent"], "value_percent") for row in realized_source["records"]}
    implied  = {int(row["timestamp"]): row for row in implied_source["records"]}
    records  = []
    for timestamp in sorted(set(realized) | set(implied)):
        rv   = realized.get(timestamp)
        raw  = implied.get(timestamp)
        ohlc = {field: (_number(raw[f"{field}_percent"], f"{field}_percent") if raw else None) for field in ("open", "high", "low", "close")}
        iv   = ohlc["close"]
        pair = rv is not None and iv is not None
        records.append({
            "timestamp": timestamp, "realized_volatility_percent": rv,
            "implied_open_percent": ohlc["open"], "implied_high_percent": ohlc["high"],
            "implied_low_percent": ohlc["low"], "implied_close_percent": iv,
            "spread_volatility_points": _clean(rv - iv) if pair else None,
            "implied_premium_volatility_points": _clean(iv - rv) if pair else None,
            "realized_to_implied_ratio": _clean(rv / iv) if pair and iv > 0 else None,
            "pair_status": "available" if pair else "partial",
        })
    aligned = [row for row in records if row["pair_status"] == "available"]
    if not records:
        status, reason = "unavailable", "volatility_sources_unavailable"
    elif not aligned or len(aligned) != len(records) or realized_source["status"] != "available" or implied_source["status"] != "available":
        status, reason = "partial", "volatility_pairs_incomplete"
    else:
        status, reason = "available", None
    current = {
        "latest_realized": ({"timestamp": max(realized), "value_percent": realized[max(realized)]} if realized else None),
        "latest_implied": ({"timestamp": max(implied), "close_percent": _number(implied[max(implied)]["close_percent"], "close_percent")} if implied else None),
        "latest_aligned_pair": (deepcopy(aligned[-1]) if aligned else None),
    }
    return {"status": status, "reason": reason, "interval": "1h", "interval_seconds": BASE_INTERVAL_SECONDS, "records": records, "current": current, **_history(records)}


def calculate_spread_metrics(comparison: Mapping[str, Any]) -> dict[str, Any]:
    aligned = [row for row in comparison["records"] if row["spread_volatility_points"] is not None]
    if not aligned:
        return {
            "status": "unavailable", "reason": "no_aligned_volatility_pairs", "basis": "realized_minus_implied",
            "aggregation": "arithmetic_mean", "window": "7d", "window_seconds": 604800, "expected_records": 168,
            "records_used": 0, "coverage": 0.0, "window_start_timestamp": None, "window_end_timestamp": None,
            "value": None, "unit": "volatility_points",
        }
    end    = aligned[-1]["timestamp"]
    start  = end - (SPREAD_WINDOW_HOURS - 1) * BASE_INTERVAL_SECONDS
    window = [row["spread_volatility_points"] for row in aligned if start <= row["timestamp"] <= end]
    count  = len(window)
    status = "available" if count >= SPREAD_MIN_VALID_RECORDS else "partial"
    return {
        "status": status, "reason": None if status == "available" else "insufficient_7d_coverage",
        "basis": "realized_minus_implied", "aggregation": "arithmetic_mean", "window": "7d", "window_seconds": 604800,
        "expected_records": 168, "records_used": count, "coverage": min(count / SPREAD_WINDOW_HOURS, 1.0),
        "window_start_timestamp": start, "window_end_timestamp": end, "value": _clean(calculate_mean(window)), "unit": "volatility_points",
    }


def calculate_trailing_statistics(values: Sequence[float | None]) -> list[tuple[float | None, float | None]]:
    output = []
    for index in range(len(values)):
        window = [value for value in values[max(0, index - ZSCORE_WINDOW_DAYS + 1):index + 1] if value is not None]
        if len(window) < ZSCORE_MIN_VALID_RECORDS:
            output.append((None, None))
        else:
            output.append((_clean(calculate_mean(window)), _clean(calculate_standard_deviation(window, ddof=ZSCORE_DDOF))))
    return output


def calculate_trailing_z_scores(values: Sequence[float | None], statistics: Sequence[tuple[float | None, float | None]] | None = None) -> list[float | None]:
    stats = list(statistics) if statistics is not None else calculate_trailing_statistics(values)
    return [None if value is None or mean is None or deviation in (None, 0) else _clean((value - mean) / deviation) for value, (mean, deviation) in zip(values, stats)]


def calculate_trailing_percentile_ranks(values: Sequence[float | None]) -> list[float | None]:
    output = []
    for index, current in enumerate(values):
        window = [value for value in values[max(0, index - PERCENTILE_WINDOW_DAYS + 1):index + 1] if value is not None]
        if current is None or len(window) < PERCENTILE_MIN_VALID_RECORDS:
            output.append(None)
        else:
            lower = sum(value < current for value in window)
            equal = sum(value == current for value in window)
            output.append(_clean((lower + 0.5 * equal) / len(window)))
    return output


def build_daily_regime_basis(positioning: Mapping[str, Any], comparison: Mapping[str, Any]) -> dict[str, Any]:
    days: dict[int, dict[str, list[dict[str, Any]]]] = {}
    for record in comparison["records"]:
        day = record["timestamp"] - record["timestamp"] % DAY_SECONDS
        days.setdefault(day, {"volatility": [], "positioning": []})["volatility"].append(record)
    for record in positioning["records"]:
        day = record["timestamp"] - record["timestamp"] % DAY_SECONDS
        days.setdefault(day, {"volatility": [], "positioning": []})["positioning"].append(record)
    records = []
    for day in sorted(days):
        volatility = days[day]["volatility"]
        positions  = days[day]["positioning"]
        rv_rows    = [row for row in volatility if row["realized_volatility_percent"] is not None]
        iv_rows    = [row for row in volatility if row["implied_close_percent"] is not None]
        rv_row     = rv_rows[-1] if rv_rows else None
        iv_row     = iv_rows[-1] if iv_rows else None
        pos        = positions[-1] if positions else None
        rv, iv     = (rv_row["realized_volatility_percent"] if rv_row else None), (iv_row["implied_close_percent"] if iv_row else None)
        asofs      = [row["timestamp"] for row in (rv_row, iv_row, pos) if row]
        if rv is not None and iv is not None and pos:
            status, reason = "available", None
        elif rv is not None and iv is not None:
            status, reason = "partial", "positioning_context_unavailable"
        elif rv is not None or iv is not None:
            status, reason = "partial", "volatility_pair_incomplete"
        elif pos:
            status, reason = "partial", "volatility_data_unavailable"
        else:
            status, reason = "unavailable", "no_daily_data"
        records.append({
            "timestamp": day, "data_as_of": max(asofs) if asofs else None,
            "realized_data_as_of": rv_row["timestamp"] if rv_row else None, "implied_data_as_of": iv_row["timestamp"] if iv_row else None,
            "positioning_data_as_of": pos["timestamp"] if pos else None, "realized_volatility_percent": rv,
            "implied_volatility_percent": iv, "spread_volatility_points": _clean(rv - iv) if rv is not None and iv is not None else None,
            "long_percent": pos["long_percent"] if pos else None, "short_percent": pos["short_percent"] if pos else None,
            "long_short_ratio": pos["long_short_ratio"] if pos else None,
            "net_long_percentage_points": pos["net_long_percentage_points"] if pos else None,
            "coverage": {"realized_hourly_records": len(rv_rows), "implied_hourly_records": len(iv_rows),
                         "positioning_hourly_records": len(positions), "aligned_volatility_records": sum(row["pair_status"] == "available" for row in volatility)},
            "status": status, "reason": reason,
        })
    metric_names = (("realized", "realized_volatility_percent"), ("implied", "implied_volatility_percent"), ("spread", "spread_volatility_points"))
    warnings     = []
    for prefix, field in metric_names:
        values  = [row[field] for row in records]
        stats   = calculate_trailing_statistics(values)
        zscores = calculate_trailing_z_scores(values, stats)
        ranks   = calculate_trailing_percentile_ranks(values)
        for row, (mean, deviation), zscore, rank in zip(records, stats, zscores, ranks):
            row[f"{prefix}_rolling_mean_30d"] = mean
            row[f"{prefix}_rolling_std_30d"]  = deviation
            row[f"{prefix}_z_score_30d"]      = zscore
            row[f"{prefix}_percentile_rank_90d"] = rank
            if deviation == 0:
                warnings.append("zero_variance_window")
    current = next((deepcopy(row) for row in reversed(records) if row["realized_volatility_percent"] is not None and row["implied_volatility_percent"] is not None
                    and row["realized_percentile_rank_90d"] is not None and row["implied_percentile_rank_90d"] is not None), None)
    if current:
        status = "available" if all(row["status"] == "available" for row in records) else "partial"
        reason = None if status == "available" else "daily_history_partial"
    elif records:
        status, reason = "partial", "classification_warmup_incomplete"
    else:
        status, reason = "unavailable", "no_daily_data"
    return {"status": status, "reason": reason, "aggregation": DAILY_AGGREGATION, "records": records, "current": current,
            "warnings": sorted(set(warnings)), **_history(records)}


def evaluate_volatility_market_regimes_processing_quality(features: Mapping[str, Any], source_availability: Mapping[str, Any], errors: Sequence[str] = ()) -> dict[str, Any]:
    required   = ["positioning", "volatility_comparison", "spread_metrics", "daily_regime_basis"]
    groups     = {status: [name for name in required if features[name]["status"] == status] for status in _STATUSES}
    source_bad = any(source["status"] != "available" for source in source_availability.values())
    warnings   = list(features["daily_regime_basis"].get("warnings", []))
    warmup     = features["daily_regime_basis"].get("current") is not None
    if errors or groups["invalid"]:
        status = "invalid"
    elif source_bad or groups["partial"] or groups["unavailable"] or not warmup:
        status = "partial"
    else:
        status = "ok"
    recovery = source_bad or features["volatility_comparison"]["status"] in {"partial", "unavailable"} or features["spread_metrics"]["status"] == "unavailable"
    return {
        "status": status, "required_features": required, "available_features": groups["available"],
        "partial_features": groups["partial"], "unavailable_features": groups["unavailable"], "invalid_features": groups["invalid"],
        "calculation_history_complete": not source_bad, "warmup_complete": warmup, "recovery_required": recovery,
        "warnings": sorted(set(warnings)), "errors": list(errors),
    }


def _source_availability(sources: Mapping[str, Any]) -> dict[str, Any]:
    return {key: {"status": value["status"], "reason": value.get("reason"),
                  "source_data_as_of": value["records"][-1]["timestamp"] if value["records"] else None} for key, value in sources.items()}


def _context(contract: Mapping[str, Any]) -> dict[str, Any]:
    dimensions = contract.get("dimensions") if isinstance(contract.get("dimensions"), Mapping) else {}
    return {
        "reference_timestamp": int(contract.get("reference_timestamp", 0)) if isinstance(contract.get("reference_timestamp"), Integral) else 0,
        "input_execution_timestamp": int(contract.get("execution_timestamp", 0)) if isinstance(contract.get("execution_timestamp"), Integral) else 0,
        "asset": dimensions.get("asset"), "symbol": dimensions.get("symbol"), "exchange": dimensions.get("exchange"), "base_interval": dimensions.get("interval"),
        "units": {"volatility": "percent", "spread": "volatility_points", "positioning_ratio": "ratio", "positioning_percent": "percent", "percentile_rank": "decimal"},
        "parameters": {"spread_window_hours": SPREAD_WINDOW_HOURS, "spread_min_valid_records": SPREAD_MIN_VALID_RECORDS,
                       "zscore_window_days": ZSCORE_WINDOW_DAYS, "zscore_min_valid_records": ZSCORE_MIN_VALID_RECORDS, "zscore_ddof": ZSCORE_DDOF,
                       "percentile_window_days": PERCENTILE_WINDOW_DAYS, "percentile_min_valid_records": PERCENTILE_MIN_VALID_RECORDS, "daily_aggregation": DAILY_AGGREGATION},
        "history_policy": {"calculation": PROCESSING_RECALCULATION_POLICY, "presentation": "not_applied_in_processing", "recalculation": "full_recompute_from_preprocessed_input"},
    }


def _invalid_output(contract: Any, error: str) -> dict[str, Any]:
    source   = {key: {"status": "invalid", "reason": "input_contract_invalid", "source_data_as_of": None} for key, _, _ in _SOURCES}
    features = {name: {"status": "invalid", "reason": "input_contract_invalid", "records": [], "current": None} for name in ("positioning", "volatility_comparison", "daily_regime_basis")}
    features["spread_metrics"] = {"status": "invalid", "reason": "input_contract_invalid", "value": None}
    safe    = contract if isinstance(contract, Mapping) else {}
    quality = evaluate_volatility_market_regimes_processing_quality(features, source, [error])
    return {"family": "volatility_market_regimes", "stage": "processing", "version": "0.1.0", "mode": safe.get("mode") if safe.get("mode") in _MODES else "bootstrap",
            "context": _context(safe), "source_availability": source, "features": features, "quality": quality}


class VolatilityMarketRegimesProcessor:
    def __init__(self, feature_builder: VolatilityMarketRegimesFeatureBuilder | None = None) -> None:
        self.feature_builder = feature_builder or VolatilityMarketRegimesFeatureBuilder()

    def process(self, contract: Any) -> dict[str, Any]:
        try:
            validate_volatility_market_regimes_input(contract)
            sources      = extract_processing_source_records(contract)
            positioning  = build_positioning_series(sources["coinglass.top_position_ratio"])
            comparison   = build_volatility_comparison_series(sources["glassnode.realized_volatility"], sources["deribit.volatility_index"])
            spread       = calculate_spread_metrics(comparison)
            daily        = build_daily_regime_basis(positioning, comparison)
            features     = self.feature_builder.build(positioning, comparison, spread, daily)
            availability = _source_availability(sources)
            quality      = evaluate_volatility_market_regimes_processing_quality(features, availability)
            return {"family": "volatility_market_regimes", "stage": "processing", "version": "0.1.0", "mode": contract["mode"],
                    "context": _context(contract), "source_availability": availability, "features": features, "quality": quality}
        except (TypeError, ValueError, KeyError) as exc:
            return _invalid_output(contract, str(exc))


def process_volatility_market_regimes(contract: Any) -> dict[str, Any]:
    return VolatilityMarketRegimesProcessor().process(contract)
