"""Liquidity Microstructure Processing v0.1."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
import math
import time
from typing import Any

from ..math.microstructure.order_book import depth_metrics, derive_cumulative_band, process_order_book_levels
from ..math.microstructure.series_metrics import absolute_change, observation_at_or_before, rolling_mean, rolling_std, rolling_z_score, safe_percent_change
from ..math.microstructure.trade_flow import aggregate_trade_window, enrich_trade_event
from .liquidity_microstructure_feature_builder import build_liquidity_microstructure_features

PROCESSING_VERSION                  = "0.1"
MARKETS                             = ("spot", "perpetual")
TIMEFRAMES                          = ("1m", "5m", "15m", "1h")
DEPTH_RANGES_PERCENT                = (1, 5, 10)
REFERENCE_DEPTH_RANGE_PERCENT       = 10
MARKET_IMPACT_QUANTITY_BASE         = 1.0
LARGE_TRADE_WINDOWS_SECONDS         = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "24h": 86400}
WHALE_ROLLING_LOOKBACK              = 20
MARKET_HISTORY_WINDOWS_DAYS         = (1, 7, 30)
DATASET_STATUSES                    = {"available", "partial", "unavailable", "invalid"}
INPUT_QUALITY_STATUSES              = {"ok", "partial", "invalid"}


def _number(value: Any, field: str, *, positive: bool = False, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"invalid_numeric:{field}")
    if (positive and value <= 0) or (nonnegative and value < 0):
        raise ValueError(f"invalid_numeric_range:{field}")
    return float(value)


def _timestamp(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("invalid_timestamp")
    return value


def _validate_dataset(dataset: Any, *, events: bool = False, kind: str) -> None:
    if not isinstance(dataset, Mapping) or dataset.get("status") not in DATASET_STATUSES or "reason" not in dataset:
        raise ValueError(f"invalid_dataset:{kind}")
    rows = dataset.get("events" if events else "records")
    if not isinstance(rows, list):
        raise ValueError(f"invalid_dataset_rows:{kind}")
    identities: dict[Any, str] = {}
    previous = 0
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(f"invalid_record:{kind}")
        timestamp = _timestamp(row.get("timestamp"))
        if timestamp < previous:
            raise ValueError(f"records_not_chronological:{kind}")
        previous = timestamp
        identity = row.get("event_id") if events else (timestamp, row.get("timeframe"), row.get("range_percent"))
        fingerprint = json.dumps(row, sort_keys=True, allow_nan=False)
        if identity in identities and identities[identity] != fingerprint:
            raise ValueError(f"incompatible_duplicate:{kind}")
        identities[identity] = fingerprint
        if events:
            if not isinstance(row.get("event_id"), str) or not row["event_id"] or row.get("side") not in {"buy", "sell"}:
                raise ValueError("invalid_trade_event")
            _number(row.get("price"), "price", positive=True)
            _number(row.get("volume_usd"), "volume_usd", nonnegative=True)
        elif kind == "orderbook":
            if row.get("market_type") not in MARKETS or row.get("timeframe") not in TIMEFRAMES:
                raise ValueError("invalid_orderbook_dimensions")
            for side in ("bid_levels", "ask_levels"):
                for level in row.get(side, []):
                    _number(level.get("price"), "price", positive=True)
                    _number(level.get("quantity"), "quantity", nonnegative=True)
        elif kind == "order_depth":
            if row.get("market_type") not in MARKETS or row.get("timeframe") not in TIMEFRAMES or row.get("range_percent") not in DEPTH_RANGES_PERCENT:
                raise ValueError("invalid_depth_dimensions")
            for field in ("bids_usd", "asks_usd", "bids_quantity", "asks_quantity"):
                _number(row.get(field), field, nonnegative=True)
        elif kind == "whale":
            if row.get("timeframe") not in TIMEFRAMES:
                raise ValueError("invalid_whale_timeframe")
            _number(row.get("whale_index_value"), "whale_index_value")
        elif kind == "market":
            _number(row.get("price"), "price", positive=True)
            _number(row.get("market_cap"), "market_cap", nonnegative=True)
            _number(row.get("circulating_supply"), "circulating_supply", nonnegative=True)


def validate_liquidity_microstructure_input(input_contract: Mapping[str, Any]) -> None:
    if not isinstance(input_contract, Mapping) or input_contract.get("family") != "liquidity_microstructure":
        raise ValueError("invalid_input_family")
    if input_contract.get("stage") != "input" or input_contract.get("mode") not in {"bootstrap", "incremental", "recovery"}:
        raise ValueError("invalid_input_stage_or_mode")
    _timestamp(input_contract.get("reference_timestamp"))
    _timestamp(input_contract.get("execution_timestamp"))
    if not isinstance(input_contract.get("context"), Mapping):
        raise ValueError("invalid_input_context")
    provider = input_contract.get("providers", {}).get("coinglass") if isinstance(input_contract.get("providers"), Mapping) else None
    quality = input_contract.get("quality")
    if not isinstance(provider, Mapping) or not isinstance(quality, Mapping) or quality.get("status") not in INPUT_QUALITY_STATUSES:
        raise ValueError("invalid_input_provider_or_quality")
    for market in MARKETS:
        _validate_dataset(provider["orderbook"][market], kind="orderbook")
        _validate_dataset(provider["order_depth"][market], kind="order_depth")
        _validate_dataset(provider["large_trades"][market], events=True, kind="trades")
    _validate_dataset(provider["whale_activity"], kind="whale")
    _validate_dataset(provider["market_history"], kind="market")
    json.dumps(input_contract, ensure_ascii=False, allow_nan=False)


def _provenance(path: str, dataset: Mapping[str, Any], timestamp: int | None, method: str, units: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
    return {"source_dataset": path, "source_status": dataset["status"], "source_timestamp": timestamp,
            "parameters": dict(parameters), "calculation_method": method, "units": units}


def _orderbooks(dataset: Mapping[str, Any], market: str, impact_quantity: float) -> dict[str, Any]:
    path = f"providers.coinglass.orderbook.{market}"
    timeframes = {}
    for timeframe in TIMEFRAMES:
        source = [record for record in dataset["records"] if record.get("timeframe") == timeframe]
        history = []
        for record in source:
            base = {key: record.get(key) for key in ("timestamp", "market_type", "exchange", "symbol", "timeframe")}
            if "bid_levels" not in record or "ask_levels" not in record:
                calculated = {"status": "unavailable", "reason": "orderbook_side_mapping_unverified"}
            else:
                calculated = process_order_book_levels(record["bid_levels"], record["ask_levels"], impact_quantity=impact_quantity)
            history.append({**base, **calculated,
                            "provenance": _provenance(path, dataset, record["timestamp"], "verified_orderbook_levels", "base_and_quote", {"impact_quantity_base": impact_quantity})})
        valid = [record for record in history if record["status"] == "available"]
        status = "available" if valid else ("invalid" if any(record["status"] == "invalid" for record in history) else "unavailable")
        reason = None if valid else (history[-1]["reason"] if history else dataset.get("reason") or "no_usable_orderbook_snapshots")
        timeframes[timeframe] = {"status": status, "reason": reason, "history": history,
                                 "current": max(valid, key=lambda record: record["timestamp"]) if valid else None,
                                 "metadata": {"records_available": len(history), "first_timestamp": min((r["timestamp"] for r in history), default=None),
                                              "last_timestamp": max((r["timestamp"] for r in history), default=None),
                                              "current_timestamp": max((r["timestamp"] for r in valid), default=None),
                                              "source_status": dataset["status"], "history_truncated": False}}
    aggregate = "invalid" if any(value["status"] == "invalid" for value in timeframes.values()) else (
        "available" if all(value["status"] == "available" for value in timeframes.values()) else "partial")
    return {"status": aggregate, "reason": None if aggregate == "available" else "one_or_more_timeframes_unavailable", "timeframes": timeframes}


def _direct_depth(record: Mapping[str, Any], dataset: Mapping[str, Any], path: str) -> dict[str, Any]:
    base = depth_metrics(float(record["bids_quantity"]), float(record["asks_quantity"]))
    quote = depth_metrics(float(record["bids_usd"]), float(record["asks_usd"]))
    return {**deepcopy(dict(record)), "status": "available" if base["status"] == quote["status"] == "available" else "unavailable",
            "reason": None if base["status"] == quote["status"] == "available" else "zero_total_depth",
            "source_type": "provider_aggregated_depth", "base_quantity": base, "quote_notional": quote,
            "source_fields": ["bids_usd", "asks_usd", "bids_quantity", "asks_quantity"],
            "provenance": _provenance(path, dataset, record["timestamp"], "provider_cumulative_depth", "base_and_quote", {"range_percent": record["range_percent"]})}


def _depth(dataset: Mapping[str, Any], market: str) -> dict[str, Any]:
    path = f"providers.coinglass.order_depth.{market}"
    timeframes = {}
    for timeframe in TIMEFRAMES:
        source = [record for record in dataset["records"] if record["timeframe"] == timeframe]
        direct = [_direct_depth(record, dataset, path) for record in source]
        by_key = {(record["timestamp"], record["range_percent"]): record for record in source}
        derived = []
        for timestamp in sorted({record["timestamp"] for record in source}):
            if (timestamp, 1) in by_key and (timestamp, 5) in by_key:
                derived.append({"timestamp": timestamp, **derive_cumulative_band(by_key[(timestamp, 1)], by_key[(timestamp, 5)], name="one_to_five")})
            if (timestamp, 5) in by_key and (timestamp, 10) in by_key:
                derived.append({"timestamp": timestamp, **derive_cumulative_band(by_key[(timestamp, 5)], by_key[(timestamp, 10)], name="five_to_ten")})
        status = "invalid" if any(item["status"] == "invalid" for item in derived) else ("available" if direct else "unavailable")
        timeframes[timeframe] = {"status": status, "reason": "non_monotonic_cumulative_depth" if status == "invalid" else (None if direct else dataset.get("reason")),
                                 "direct_ranges": direct, "derived_bands": derived}
    aggregate = "invalid" if any(value["status"] == "invalid" for value in timeframes.values()) else (
        "available" if all(value["status"] == "available" for value in timeframes.values()) else "partial")
    return {"status": aggregate, "reason": None if aggregate == "available" else "one_or_more_timeframes_unavailable", "timeframes": timeframes}


def _trades(dataset: Mapping[str, Any], market: str, reference: int) -> dict[str, Any]:
    observed = [enrich_trade_event(event) for event in dataset["events"]]
    large = [event for event in observed if event["meets_configured_threshold"]]
    windows = {name: aggregate_trade_window(large, window_end=reference, window_seconds=seconds)
               for name, seconds in LARGE_TRADE_WINDOWS_SECONDS.items()}
    status = "partial" if dataset["status"] == "partial" else ("available" if dataset["status"] == "available" else dataset["status"])
    return {"status": status, "reason": dataset.get("reason"), "observed_events": observed, "large_trade_events": large, "windows": windows,
            "coverage": {"observed_first_timestamp": min((event["timestamp"] for event in observed), default=None),
                         "observed_last_timestamp": max((event["timestamp"] for event in observed), default=None),
                         "observed_span_seconds": (max(event["timestamp"] for event in observed) - min(event["timestamp"] for event in observed)) if observed else 0,
                         "coverage_complete": False, "reason": "source_collection_window_not_exposed"},
            "provenance": _provenance(f"providers.coinglass.large_trades.{market}", dataset, max((e["timestamp"] for e in observed), default=None),
                                      "threshold_flag_filter_and_window_aggregation", "usd_and_base", LARGE_TRADE_WINDOWS_SECONDS)}


def _whale(dataset: Mapping[str, Any], lookback: int) -> dict[str, Any]:
    timeframes = {}
    for timeframe in TIMEFRAMES:
        records = [deepcopy(record) for record in dataset["records"] if record["timeframe"] == timeframe]
        values = [float(record["whale_index_value"]) for record in records]
        current, previous = (records[-1] if records else None), (records[-2] if len(records) > 1 else None)
        mean, std, zscore = rolling_mean(values, lookback), rolling_std(values, lookback), rolling_z_score(values, lookback)
        reason = "insufficient_data" if len(values) < lookback else ("zero_rolling_standard_deviation" if std == 0 else None)
        timeframes[timeframe] = {"status": "available" if records else "unavailable", "reason": None if records else dataset.get("reason"),
                                 "records": records, "current": current, "previous": previous,
                                 "statistics": {"status": "available" if zscore is not None else "unavailable", "reason": reason,
                                                "absolute_change": absolute_change(values[-1], values[-2]) if len(values) > 1 else None,
                                                "percent_change": safe_percent_change(values[-1], values[-2]) if len(values) > 1 else None,
                                                "rolling_mean_20": mean, "rolling_std_20": std, "rolling_z_score_20": zscore}}
    status = "available" if all(value["status"] == "available" for value in timeframes.values()) else "partial"
    return {"status": status, "reason": None if status == "available" else "one_or_more_timeframes_unavailable", "timeframes": timeframes}


def _market_history(dataset: Mapping[str, Any], reference: int) -> dict[str, Any]:
    records = [deepcopy(record) for record in dataset["records"]]
    enriched = []
    for index, record in enumerate(records):
        previous = records[index - 1] if index else None
        enriched.append({**record, "price_return_decimal": None if previous is None else record["price"] / previous["price"] - 1})
    current = enriched[-1] if enriched else None
    changes = {}
    for days in MARKET_HISTORY_WINDOWS_DAYS:
        historical = observation_at_or_before(enriched, current["timestamp"] - days * 86400) if current else None
        changes[f"{days}d"] = {"status": "available" if historical else "unavailable",
                                "reason": None if historical else "insufficient_market_history",
                                "source_timestamp": historical["timestamp"] if historical else None,
                                "change_percent": 100 * (current["price"] / historical["price"] - 1) if historical else None}
    return {"status": "available" if current else "unavailable", "reason": None if current else dataset.get("reason"),
            "records": enriched, "current": current, "changes": changes,
            "provenance": _provenance("providers.coinglass.market_history", dataset, current["timestamp"] if current else None,
                                      "historical_observation_at_or_before", "percent", {"windows_days": MARKET_HISTORY_WINDOWS_DAYS})}


def _comparison(markets: Mapping[str, Any]) -> dict[str, Any]:
    depth_rows = []
    for timeframe in TIMEFRAMES:
        spot = {(row["timestamp"], row["range_percent"]): row for row in markets["spot"]["order_depth"]["timeframes"][timeframe]["direct_ranges"]}
        perpetual = {(row["timestamp"], row["range_percent"]): row for row in markets["perpetual"]["order_depth"]["timeframes"][timeframe]["direct_ranges"]}
        for timestamp, range_percent in sorted(set(spot) & set(perpetual)):
            s, p = spot[(timestamp, range_percent)], perpetual[(timestamp, range_percent)]
            depth_rows.append({"timestamp": timestamp, "timeframe": timeframe, "range_percent": range_percent,
                               "perpetual_to_spot_total_depth_ratio_quote": None if s["quote_notional"]["total"] == 0 else p["quote_notional"]["total"] / s["quote_notional"]["total"],
                               "perpetual_to_spot_total_depth_ratio_base": None if s["base_quantity"]["total"] == 0 else p["base_quantity"]["total"] / s["base_quantity"]["total"],
                               "imbalance_difference_quote_percent": p["quote_notional"]["imbalance_percent"] - s["quote_notional"]["imbalance_percent"],
                               "imbalance_difference_base_percent": p["base_quantity"]["imbalance_percent"] - s["base_quantity"]["imbalance_percent"],
                               "net_depth_difference_quote": p["quote_notional"]["net"] - s["quote_notional"]["net"]})
    return {"spot_perpetual": {"status": "available" if depth_rows else "unavailable", "reason": None if depth_rows else "no_exact_timestamp_matches",
                               "order_depth": depth_rows}}


def _source_selection(provider: Mapping[str, Any]) -> dict[str, Any]:
    result = {}
    for market in MARKETS:
        for name, role in (("orderbook", "canonical"), ("order_depth", "canonical"), ("large_trades", "canonical")):
            dataset = provider[name][market]
            result[f"{name}_{market}"] = {"provider": "coinglass", "dataset_path": f"providers.coinglass.{name}.{market}",
                                           "source_status": dataset["status"], "selected": True, "role": role, "fallback_applied": False}
    for name, role in (("whale_activity", "proprietary_indicator"), ("market_history", "context")):
        dataset = provider[name]
        result[name] = {"provider": "coinglass", "dataset_path": f"providers.coinglass.{name}", "source_status": dataset["status"],
                        "selected": True, "role": role, "fallback_applied": False}
    return result


def _invalid_output(input_contract: Mapping[str, Any], execution_timestamp: int, configuration: Mapping[str, Any]) -> dict[str, Any]:
    return {"family": "liquidity_microstructure", "stage": "processing", "mode": input_contract.get("mode"),
            "reference_timestamp": input_contract.get("reference_timestamp"), "execution_timestamp": execution_timestamp,
            "configuration": dict(configuration), "context": deepcopy(dict(input_contract.get("context", {}))),
            "source_selection": {}, "markets": {}, "whale_activity": {}, "market_history": {},
            "comparison": {"spot_perpetual": {}}, "features": {},
            "quality": {"status": "invalid", "reason": "input_quality_invalid", "required_features": [], "optional_features": [],
                        "missing_features": [], "partial_features": [], "unavailable_features": [], "invalid_features": [], "warnings": [], "errors": []}}


def process_liquidity_microstructure(input_contract: Mapping[str, Any], *, existing_processing: Mapping[str, Any] | None = None,
                                     now_timestamp: int | None = None, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    input_copy, config_copy = deepcopy(input_contract), deepcopy(dict(config or {}))
    validate_liquidity_microstructure_input(input_copy)
    impact_quantity = float(config_copy.get("market_impact_quantity_base", MARKET_IMPACT_QUANTITY_BASE))
    lookback = int(config_copy.get("whale_rolling_lookback", WHALE_ROLLING_LOOKBACK))
    if impact_quantity <= 0 or lookback <= 0:
        raise ValueError("invalid_processing_configuration")
    configuration = {"version": PROCESSING_VERSION, "markets": list(MARKETS), "timeframes": list(TIMEFRAMES),
                     "depth_ranges_percent": list(DEPTH_RANGES_PERCENT), "reference_depth_range_percent": REFERENCE_DEPTH_RANGE_PERCENT,
                     "market_impact_quantity_base": impact_quantity, "whale_rolling_lookback": lookback}
    execution = int(now_timestamp or time.time())
    if input_copy["quality"]["status"] == "invalid":
        return _invalid_output(input_copy, execution, configuration)
    provider, reference = input_copy["providers"]["coinglass"], input_copy["reference_timestamp"]
    markets = {market: {"orderbook": _orderbooks(provider["orderbook"][market], market, impact_quantity),
                        "order_depth": _depth(provider["order_depth"][market], market),
                        "large_trades": _trades(provider["large_trades"][market], market, reference)} for market in MARKETS}
    whale, history = _whale(provider["whale_activity"], lookback), _market_history(provider["market_history"], reference)
    previous = deepcopy(existing_processing) if existing_processing is not None else None
    compatible_previous = (isinstance(previous, Mapping) and previous.get("family") == "liquidity_microstructure" and
                           previous.get("configuration") == configuration and previous.get("context") == input_copy["context"])
    if compatible_previous:
        try:
            json.dumps(previous, allow_nan=False)
        except (TypeError, ValueError):
            compatible_previous = False
    if compatible_previous:
        for market in MARKETS:
            for feature, source_name, rows_name in (("orderbook", "orderbook", "records"), ("order_depth", "order_depth", "records"),
                                                    ("large_trades", "large_trades", "events")):
                dataset = provider[source_name][market]
                if dataset["status"] == "unavailable" and not dataset[rows_name]:
                    markets[market][feature] = deepcopy(previous["markets"][market][feature])
                    markets[market][feature].update({"status": "partial", "reason": "update_failed_previous_processing_preserved",
                                                     "preserved_from_previous": True})
        if provider["whale_activity"]["status"] == "unavailable" and not provider["whale_activity"]["records"]:
            whale = deepcopy(previous["whale_activity"])
            whale.update({"status": "partial", "reason": "update_failed_previous_processing_preserved", "preserved_from_previous": True})
        if provider["market_history"]["status"] == "unavailable" and not provider["market_history"]["records"]:
            history = deepcopy(previous["market_history"])
            history.update({"status": "partial", "reason": "update_failed_previous_processing_preserved", "preserved_from_previous": True})
    comparison = _comparison(markets)
    required = {f"markets.{market}.{feature}": markets[market][feature]["status"] for market in MARKETS for feature in ("orderbook", "order_depth", "large_trades")}
    required.update({"whale_activity": whale["status"], "market_history": history["status"]})
    invalid = [name for name, status in required.items() if status == "invalid"]
    partial = [name for name, status in required.items() if status == "partial"]
    unavailable = [name for name, status in required.items() if status == "unavailable"]
    quality_status = "invalid" if invalid else ("partial" if partial or unavailable else "ok")
    output = {"family": "liquidity_microstructure", "stage": "processing", "mode": input_copy["mode"],
              "reference_timestamp": reference, "execution_timestamp": execution, "configuration": configuration,
              "context": deepcopy(dict(input_copy["context"])),
              "source_selection": _source_selection(provider), "markets": markets, "whale_activity": whale,
              "market_history": history, "comparison": comparison,
              "features": build_liquidity_microstructure_features(markets=markets, whale_activity=whale,
                                                                   market_history=history, comparison=comparison),
              "quality": {"status": quality_status, "required_features": list(required),
                          "optional_features": ["markets.spot.orderbook.market_impact", "markets.perpetual.orderbook.market_impact",
                                                "comparison.spot_perpetual", "whale_activity.rolling_statistics"],
                          "missing_features": [], "partial_features": partial, "unavailable_features": unavailable,
                          "invalid_features": invalid, "warnings": [], "errors": []}}
    json.dumps(output, ensure_ascii=False, allow_nan=False)
    return output


class LiquidityMicrostructureProcessor:
    def __init__(self, input_contract: Mapping[str, Any], *, existing_processing: Mapping[str, Any] | None = None,
                 now_timestamp: int | None = None, config: Mapping[str, Any] | None = None) -> None:
        self.arguments = {"input_contract": input_contract, "existing_processing": existing_processing,
                          "now_timestamp": now_timestamp, "config": config}

    def run(self) -> dict[str, Any]:
        return process_liquidity_microstructure(**self.arguments)
