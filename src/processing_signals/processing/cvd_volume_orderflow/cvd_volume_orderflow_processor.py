"""Orchestration and contracts for CVD volume/order-flow Processing v0.1."""
from __future__ import annotations

import copy
import math
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from .cvd_volume_orderflow_feature_builder import (
    BASE_TIMEFRAMES, CVD_VOLUME_ORDERFLOW_FAMILY, DELTA_MA_PERIOD, FLOW_EFFICIENCY_PERIOD, MARKETS, PROCESSING_STAGE,
    PROCESSING_VERSION, SOURCE_FACTOR, SOURCE_TIMEFRAME, TARGET_TIMEFRAMES, TIMEFRAME_SECONDS, CvdVolumeOrderflowFeatureBuilder,
    build_general_vwap,
)


def _sequence(value: Any) -> bool:
    return isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray))


def _clock_timestamp(clock: Callable[[], Any] | None) -> int:
    value = time.time() if clock is None else clock()
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("invalid_clock")
    return int(value)


def _iso_utc(value: int) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


class CvdVolumeOrderflowProcessor:
    def __init__(self, *, feature_builder: CvdVolumeOrderflowFeatureBuilder | None = None,
                 clock: Callable[[], Any] | None = None) -> None:
        self.feature_builder = feature_builder or CvdVolumeOrderflowFeatureBuilder()
        self.clock           = clock

    def validate_input_contract(self, input_contract: Any) -> dict[str, Any]:
        if not isinstance(input_contract, Mapping):
            raise ValueError("input_contract_must_be_mapping")
        if input_contract.get("family") != CVD_VOLUME_ORDERFLOW_FAMILY:
            raise ValueError("incompatible_family")
        if input_contract.get("stage") != "input":
            raise ValueError("incompatible_stage")
        if input_contract.get("mode") not in {"bootstrap", "incremental", "recovery"}:
            raise ValueError("invalid_mode")
        context, markets = input_contract.get("context"), input_contract.get("markets")
        if not isinstance(context, Mapping) or not isinstance(markets, Mapping) or set(("spot", "futures")) - set(markets):
            raise ValueError("invalid_input_structure")
        normalized = {}
        for market in ("spot", "futures"):
            payload = markets.get(market)
            if not isinstance(payload, Mapping):
                raise ValueError("invalid_market_structure")
            timeframes = payload.get("cvd", {}).get("timeframes") if isinstance(payload.get("cvd"), Mapping) else None
            if not isinstance(timeframes, Mapping) or set(BASE_TIMEFRAMES) - set(timeframes):
                raise ValueError("missing_base_timeframes")
            normalized[market] = {}
            for timeframe in BASE_TIMEFRAMES:
                timeframe_payload = timeframes[timeframe]
                if not isinstance(timeframe_payload, Mapping) or not _sequence(timeframe_payload.get("records")):
                    raise ValueError("invalid_timeframe_payload")
                normalized[market][timeframe] = self.feature_builder.validate_base_records(timeframe_payload["records"])
        return normalized

    def build_context(self, input_contract: Mapping[str, Any], processing_timestamp: int) -> dict[str, Any]:
        context = input_contract["context"]
        required = ("base_asset", "pair_symbol", "data_mode", "is_demo", "reference_timestamp", "requested_at", "execution_timestamp")
        if any(key not in context for key in required):
            raise ValueError("incomplete_input_context")
        return {"base_asset": context["base_asset"], "pair_symbol": context["pair_symbol"], "markets": list(MARKETS),
            "base_timeframes": list(BASE_TIMEFRAMES), "available_timeframes": list(TARGET_TIMEFRAMES), "data_mode": context["data_mode"],
            "is_demo": context["is_demo"], "reference_timestamp": context["reference_timestamp"], "input_requested_at": context["requested_at"],
            "input_execution_timestamp": context["execution_timestamp"], "processing_timestamp": processing_timestamp,
            "processing_requested_at": _iso_utc(processing_timestamp)}

    def build_parameters(self) -> dict[str, Any]:
        return {"source_timeframes": copy.deepcopy(SOURCE_TIMEFRAME), "source_factors": copy.deepcopy(SOURCE_FACTOR),
            "delta_ma_period": DELTA_MA_PERIOD, "flow_efficiency_period": FLOW_EFFICIENCY_PERIOD,
            "delta_ma": {"method": "simple_moving_average", "period": DELTA_MA_PERIOD, "source_field": "volume_delta_usd"},
            "flow_efficiency": {"method": "net_delta_displacement_over_absolute_delta_path", "period": FLOW_EFFICIENCY_PERIOD, "unit": "decimal"},
            "cvd_anchor_method": "zero_before_first_available_record", "general_method": "aligned_spot_plus_futures",
            "resampling_alignment": "utc_epoch", "recalculation_policy": "full_history_deterministic_rebuild",
            "cvd_ohlc": {"construction": "derived_from_interval_volume_delta_path", "native_ohlc": False},
            "provider_reference_used_in_calculation": False}

    def evaluate_availability(self, records: Sequence[Mapping[str, Any]], *, input_status: str = "available",
                              alignment_complete: bool = True) -> tuple[str, str | None]:
        if not records:
            return "unavailable", "no_records"
        if input_status == "invalid":
            return "invalid", "input_dataset_invalid"
        if input_status in {"partial", "unavailable"}:
            return "partial", "input_dataset_partial"
        if not alignment_complete:
            return "partial", "spot_futures_timestamp_misalignment"
        current = records[-1]
        if any(row["is_partial"] for row in records):
            return "partial", "incomplete_source_bucket"
        if current["continuity_status"] == "broken":
            return "partial", "cvd_continuity_broken_by_missing_intervals"
        if current["delta_ma_21_usd"] is None or current["flow_efficiency"]["status"] != "available":
            return "partial", "rolling_warmup_incomplete"
        return "available", None

    def _timeframe_contract(self, target: str, feature: Mapping[str, Any], *, input_status: str,
                            alignment_complete: bool = True) -> dict[str, Any]:
        records = copy.deepcopy(feature["records"])
        status, reason = self.evaluate_availability(records, input_status=input_status, alignment_complete=alignment_complete)
        return {"status": status, "reason": reason, "source_timeframe": SOURCE_TIMEFRAME[target], "target_timeframe": target,
            "interval_seconds": TIMEFRAME_SECONDS[target], "source_factor": SOURCE_FACTOR[target], "records_available": len(records),
            "first_timestamp": records[0]["timestamp"] if records else None, "last_timestamp": records[-1]["timestamp"] if records else None,
            "current_timestamp": records[-1]["timestamp"] if records else None,
            "complete_records": sum(not row["is_partial"] for row in records), "partial_records": sum(row["is_partial"] for row in records),
            "gap_count": len(feature["continuity_breaks"]), "continuity_break_count": len(feature["continuity_breaks"]),
            "continuity_breaks": copy.deepcopy(feature["continuity_breaks"]), "anchor_method": feature["anchor_method"],
            "anchor_timestamp": feature["anchor_timestamp"], "anchor_value_usd": feature["anchor_value_usd"],
            "history_relative": feature["history_relative"], "construction": feature["construction"], "native_ohlc": feature["native_ohlc"],
            "provider_reference_used_in_calculation": False, "records": records,
            "current": copy.deepcopy(records[-1]) if records else None}

    def process_market(self, market: str, base_records: Mapping[str, Sequence[Mapping[str, Any]]],
                       input_market: Mapping[str, Any]) -> dict[str, Any]:
        features = self.feature_builder.build_market_features(base_records)
        timeframes = {}
        for target in TARGET_TIMEFRAMES:
            source = SOURCE_TIMEFRAME[target]
            input_status = input_market["cvd"]["timeframes"][source].get("status", "available")
            timeframes[target] = self._timeframe_contract(target, features[target], input_status=input_status)
        summaries = {name: self.feature_builder.build_fixed_window_summary(timeframes["15m"]["records"], name) for name in ("1h", "24h")}
        footprint = self.feature_builder.build_footprint_vwap(input_market.get("footprint"))
        availability = {"timeframes": {target: {"status": payload["status"], "reason": payload["reason"]} for target, payload in timeframes.items()},
            "window_summaries": {name: {"status": payload["status"], "reason": payload["reason"]} for name, payload in summaries.items()},
            "footprint_vwap": {"status": footprint["status"], "reason": footprint["reason"]}}
        return {"timeframes": timeframes, "window_summaries": summaries, "footprint_summaries": {"1h": footprint},
            "price_vs_vwap": {}, "availability": availability}

    def process_general(self, spot_base: Mapping[str, Sequence[Mapping[str, Any]]], futures_base: Mapping[str, Sequence[Mapping[str, Any]]],
                        spot_result: Mapping[str, Any], futures_result: Mapping[str, Any]) -> dict[str, Any]:
        bases, alignment = {}, {}
        for timeframe in BASE_TIMEFRAMES:
            bases[timeframe], alignment[timeframe] = self.feature_builder.build_general_base(spot_base[timeframe], futures_base[timeframe])
        features, timeframes = self.feature_builder.build_market_features(bases), {}
        for target in TARGET_TIMEFRAMES:
            source = SOURCE_TIMEFRAME[target]
            input_status = "available" if bases[source] else "unavailable"
            timeframes[target] = self._timeframe_contract(target, features[target], input_status=input_status,
                alignment_complete=alignment[source]["alignment_complete"])
            timeframes[target]["alignment"] = copy.deepcopy(alignment[source])
        summaries = {name: self.feature_builder.build_fixed_window_summary(timeframes["15m"]["records"], name) for name in ("1h", "24h")}
        footprint = build_general_vwap(spot_result["footprint_summaries"]["1h"], futures_result["footprint_summaries"]["1h"])
        availability = {"timeframes": {target: {"status": payload["status"], "reason": payload["reason"]} for target, payload in timeframes.items()},
            "window_summaries": {name: {"status": payload["status"], "reason": payload["reason"]} for name, payload in summaries.items()},
            "footprint_vwap": {"status": footprint["status"], "reason": footprint["reason"]}}
        return {"timeframes": timeframes, "window_summaries": summaries, "footprint_summaries": {"1h": footprint},
            "price_vs_vwap": {}, "availability": availability, "alignment": alignment}

    def evaluate_quality(self, markets: Mapping[str, Any], input_quality: Mapping[str, Any]) -> dict[str, Any]:
        core = [markets[market]["timeframes"][timeframe]["status"] for market in MARKETS for timeframe in TARGET_TIMEFRAMES]
        enrichments = [markets[market]["footprint_summaries"]["1h"]["status"] for market in MARKETS]
        enrichments.extend(markets[market]["price_vs_vwap"]["status"] for market in MARKETS)
        summaries = [markets[market]["window_summaries"][window]["status"] for market in MARKETS for window in ("1h", "24h")]
        core_status = "invalid" if "invalid" in core or input_quality.get("status") == "invalid" else ("available" if all(item == "available" for item in core + summaries) else "partial")
        enrichment_status = "available" if all(item == "available" for item in enrichments) else "partial"
        status = "invalid" if core_status == "invalid" else ("ok" if core_status == enrichment_status == "available" else "partial")
        warnings = [f"{market}.{timeframe}:{markets[market]['timeframes'][timeframe]['reason']}" for market in MARKETS for timeframe in TARGET_TIMEFRAMES
            if markets[market]["timeframes"][timeframe]["status"] != "available"]
        warnings.extend(f"input_quality:{input_quality.get('status')}" for _ in [0] if input_quality.get("status") not in {None, "ok"})
        errors = [item for item in warnings if "invalid" in item]
        return {"status": status, "core_status": core_status, "enrichment_status": enrichment_status,
            "warnings": warnings, "errors": errors}

    def run(self, input_contract: Mapping[str, Any], *, price_reference_by_market: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any]:
        normalized = self.validate_input_contract(input_contract)
        processing_timestamp = _clock_timestamp(self.clock)
        input_markets = input_contract["markets"]
        spot = self.process_market("spot", normalized["spot"], input_markets["spot"])
        futures = self.process_market("futures", normalized["futures"], input_markets["futures"])
        general = self.process_general(normalized["spot"], normalized["futures"], spot, futures)
        markets = {"spot": spot, "futures": futures, "general": general}
        references = price_reference_by_market or {}
        if not isinstance(references, Mapping) or set(references) - set(MARKETS):
            raise ValueError("invalid_price_reference_markets")
        for market in MARKETS:
            markets[market]["price_vs_vwap"] = self.feature_builder.build_price_vs_vwap(
                markets[market]["footprint_summaries"]["1h"], references.get(market))
            markets[market]["availability"]["price_vs_vwap"] = {"status": markets[market]["price_vs_vwap"]["status"],
                "reason": markets[market]["price_vs_vwap"]["reason"]}
        quality = self.evaluate_quality(markets, input_contract.get("quality", {}))
        return {"family": CVD_VOLUME_ORDERFLOW_FAMILY, "stage": PROCESSING_STAGE, "version": PROCESSING_VERSION,
            "mode": input_contract["mode"], "context": self.build_context(input_contract, processing_timestamp),
            "parameters": self.build_parameters(), "markets": markets, "quality": quality}


def process_cvd_volume_orderflow(input_contract: Mapping[str, Any], *, price_reference_by_market: Mapping[str, Mapping[str, Any]] | None = None,
                                 clock: Callable[[], Any] | None = None) -> dict[str, Any]:
    return CvdVolumeOrderflowProcessor(clock=clock).run(input_contract, price_reference_by_market=price_reference_by_market)
