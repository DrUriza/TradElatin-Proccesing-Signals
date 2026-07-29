from __future__ import annotations

import copy
import json
import math
from collections.abc import Mapping, Sequence

import pytest

from processing_signals.processing.on_chain_miners.on_chain_miners_feature_builder import (
    SECONDS_PER_DAY,
    UTXO_AGE_BANDS,
    build_miner_outflow_distribution,
    build_miner_outflow_total_series,
    build_miner_revenue_breakdown,
    build_miners_unspent_supply_series,
    build_nupl_phase_basis,
    build_nupl_series,
    build_reserve_age_context,
    build_current_snapshot,
    build_difficulty_trillion_series,
    build_hashrate_eh_s_series,
    build_miner_net_position_change_series,
    build_reserve_trend_features,
    build_sopr_7d_series,
)
from processing_signals.processing.on_chain_miners.on_chain_miners_processor import OnChainMinersProcessor, process_on_chain_miners


DAY   = SECONDS_PER_DAY
START = 1_775_000_000 - (1_775_000_000 % DAY)


def _records(metric_id, count=100, *, start=START):
    records = []
    for index in range(count):
        timestamp = start + index * DAY
        if metric_id == "miner_reserve":
            records.append({"timestamp": timestamp, "value": 1_000_000.0 + 10 * index, "unit": "BTC", "provider": "glassnode"})
        elif metric_id == "sopr":
            value = 0.97 + index * 0.01
            records.append({"timestamp": timestamp, "value": value, "sopr": value, "a_sopr": value + 10, "sth_sopr": None,
                            "lth_sopr": value - 10, "unit": "ratio", "provider": "cryptoquant"})
        elif metric_id == "hashrate":
            records.append({"timestamp": timestamp, "value": 682_900_000_000_000_000_000.0 + index, "unit": "H/s", "provider": "glassnode"})
        elif metric_id == "difficulty":
            records.append({"timestamp": timestamp, "value": 94_600_000_000_000.0 + index, "unit": "provider_native_difficulty", "provider": "cryptoquant"})
        else:
            records.append({"timestamp": timestamp, "value": 1.0 + index * 0.1, "unit": "z_score", "provider": "cryptoquant"})
    return records


def input_contract(*, count=100, mode="bootstrap", input_status="ok"):
    units = {"miner_reserve": "BTC", "sopr": "ratio", "hashrate": "H/s", "difficulty": "provider_native_difficulty", "mpi": "z_score"}
    series = {}
    for metric_id, unit in units.items():
        records = _records(metric_id, count)
        series[metric_id] = {"metric_id": metric_id, "provider": records[0]["provider"] if records else None, "endpoint_id": metric_id,
                             "source_field": "value", "source_window": "day", "unit": unit, "status": "available", "incoming_records": records[-2:],
                             "records": records, "unavailable_records": [], "invalid_records": [], "gaps": [], "warnings": [], "errors": [],
                             "metadata": {"records_available": len(records)}}
    last = START + (count - 1) * DAY if count else None
    extension_specs = {"miners_unspent_supply": ("BTC", "glassnode", "miners_unspent_supply"),
                       "miner_revenue_total_usd": ("USD/day", "glassnode", "revenue_sum"),
                       "miner_block_reward_revenue_usd": ("USD/day", "glassnode", "volume_mined_sum"),
                       "miner_revenue_from_fees": ("provider_native_percentage", "glassnode", "revenue_from_fees"),
                       "nupl": ("ratio", "coinglass", "bitcoin_nupl")}
    for metric_id, (unit, provider, endpoint_id) in extension_specs.items():
        records = []
        for index in range(count):
            timestamp = START + index * DAY
            value = (2_000_000.0 + index if metric_id == "miners_unspent_supply" else 40_000_000.0 + index * 100_000 if metric_id == "miner_revenue_total_usd"
                     else 38_000_000.0 + index * 90_000 if metric_id == "miner_block_reward_revenue_usd" else 0.05 if metric_id == "miner_revenue_from_fees"
                     else 0.4 + index * 0.001)
            record = {"timestamp": timestamp, "value": value, "unit": unit, "provider": provider, "endpoint_id": endpoint_id}
            if metric_id == "nupl":
                record["price_usd"] = 100_000.0 + index
            records.append(record)
        current = ({"status": "available", "timestamp": records[-1]["timestamp"], "value": records[-1]["value"], "unit": unit,
                    **({"price_usd": records[-1]["price_usd"]} if metric_id == "nupl" else {})} if records else {"status": "unavailable", "value": None})
        series[metric_id] = {"metric_id": metric_id, "unit": unit, "status": "available" if records else "unavailable", "records": records,
                             "current": current, "warnings": [], "errors": [], "metadata": {"last_available_timestamp": last}}
    utxo_records = []
    for index in range(count):
        bands = {band: {"native_btc": float(position + 1), "usd": float((position + 1) * 1000), "percent": float(position + 1)}
                 for position, band in enumerate(UTXO_AGE_BANDS)}
        utxo_records.append({"timestamp": START + index * DAY, "bands": bands, "scope": "bitcoin_network"})
    series["utxo_age_distribution"] = {"metric_id": "utxo_age_distribution", "unit": "mixed", "status": "available", "records": utxo_records,
                                           "current": {"status": "available", "timestamp": last} if utxo_records else {"status": "unavailable"},
                                           "warnings": [], "errors": [], "metadata": {"last_available_timestamp": last}}
    def pool_records(multiplier):
        return [{"timestamp": START + index * DAY, "outflow_total": multiplier * (100 + index), "outflow_top10": multiplier * 80,
                 "outflow_mean": multiplier * 2, "unit": "BTC", "provider": "cryptoquant", "endpoint_id": "miner_outflow",
                 "source_window": "day"} for index in range(count)]
    pools = {"antpool": {"miner_symbol": "antpool", "active": True, "status": "available", "records": pool_records(2.0), "warnings": [], "errors": [],
                           "metadata": {"last_timestamp": last}},
             "f2pool": {"miner_symbol": "f2pool", "active": True, "status": "available", "records": pool_records(1.0), "warnings": [], "errors": [],
                         "metadata": {"last_timestamp": last}}}
    collections = {"miner_entities": {"metric_id": "miner_entities", "status": "available", "records": [], "warnings": [], "errors": [], "metadata": {}},
                   "miner_outflow_by_pool": {"metric_id": "miner_outflow_by_pool", "status": "available", "unit": "BTC", "pools": pools,
                                              "warnings": [], "errors": [], "metadata": {"data_as_of": last}}}
    return {"family": "on_chain_miners", "stage": "input", "mode": mode,
            "context": {"asset": "BTC", "data_mode": "synthetic", "is_demo": True, "reference_timestamp": last,
                        "execution_timestamp": last + 3600 if last else START, "generated_at": "2026-07-27T01:00:00Z", "include_enrichment": False,
                        "include_screen_extensions": True},
            "series": series, "collections": collections,
            "quality": {"status": input_status, "availability": {**{key: "available" for key in series}, **{key: "available" for key in collections}}, "data_as_of": last,
                                           "recovery_required": input_status != "ok", "warnings": [], "errors": []}}


@pytest.fixture
def processed():
    return process_on_chain_miners(input_contract())


def test_processing_output_structure(processed):
    assert set(processed) == {"family", "stage", "mode", "context", "series", "features", "quality"}


def test_processing_family_and_stage(processed):
    assert processed["family"] == "on_chain_miners" and processed["stage"] == "processing"


def test_context_preserves_runtime_metadata(processed):
    assert processed["context"]["data_mode"] == "synthetic" and processed["context"]["is_demo"] is True


def test_processing_does_not_mutate_input():
    source = input_contract()
    before = copy.deepcopy(source)
    process_on_chain_miners(source)
    assert source == before


def _keys(value):
    found = set()
    if isinstance(value, Mapping):
        found.update(value)
        for item in value.values():
            found.update(_keys(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            found.update(_keys(item))
    return found


def test_no_presentation_or_classification_keys(processed):
    forbidden = {"signal", "state", "display_signal", "signal_color_token", "display_color_token", "profit", "loss", "increasing", "decreasing",
                 "high_pressure", "low_pressure", "neutral", "charts", "widgets", "kpis", "screen"}
    assert forbidden.isdisjoint(_keys(processed))


def test_full_history_is_preserved_without_visual_window(processed):
    assert len(processed["series"]["miner_reserve_btc"]["records"]) == 100
    assert processed["context"]["calculation_history"] == "full_available_history" and processed["context"]["presentation_window"] is None
    assert all(not payload["metadata"]["history_truncated"] for payload in processed["series"].values())


@pytest.mark.parametrize("metric_id", ["miner_reserve_btc", "sopr", "sopr_7d", "hashrate_eh_s", "difficulty_t", "miner_net_position_change", "mpi"])
def test_each_required_processing_series_exists_with_current(metric_id, processed):
    assert metric_id in processed["series"] and processed["series"][metric_id]["current"]["status"] == "available"


@pytest.mark.parametrize("metric_id", ["miner_reserve_btc", "sopr", "sopr_7d", "hashrate_eh_s", "difficulty_t", "miner_net_position_change", "mpi"])
def test_each_series_declares_full_history_metadata(metric_id, processed):
    metadata = processed["series"][metric_id]["metadata"]
    assert metadata["calculation_history"] == "full_available_history" and metadata["history_truncated"] is False
    assert metadata["records_calculated"] == len(processed["series"][metric_id]["records"])


def test_base_series_publish_only_processing_fields(processed):
    reserve = processed["series"]["miner_reserve_btc"]["records"][0]
    mpi     = processed["series"]["mpi"]["records"][0]
    assert set(reserve) == {"timestamp", "value", "unit", "source_metric_id", "provider"}
    assert set(mpi) == {"timestamp", "value", "unit", "source_metric_id", "provider"}


def test_sopr_copy_preserves_nullable_auxiliary_variants(processed):
    record = processed["series"]["sopr"]["records"][0]
    assert record["sth_sopr"] is None and record["a_sopr"] is not None and record["lth_sopr"] is not None


@pytest.mark.parametrize(("metric_id", "unit"), [("miner_reserve_btc", "BTC"), ("sopr", "ratio"), ("sopr_7d", "ratio"),
                                                   ("hashrate_eh_s", "EH/s"), ("difficulty_t", "T"),
                                                   ("miner_net_position_change", "BTC/day"), ("mpi", "z_score")])
def test_processing_series_units_are_explicit(metric_id, unit, processed):
    assert processed["series"][metric_id]["unit"] == unit


@pytest.mark.parametrize(("count", "calculated"), [(6, 0), (7, 1), (8, 2)])
def test_sopr_7d_requires_seven_consecutive_days(count, calculated):
    result = build_sopr_7d_series(_records("sopr", count))
    assert len(result["records"]) == calculated


def test_sopr_7d_manual_mean_uses_only_general_sopr():
    records = _records("sopr", 7)
    for index, record in enumerate(records):
        record.update({"sopr": 0.97 + index * 0.01, "value": 99.0, "a_sopr": -999.0, "sth_sopr": 999.0, "lth_sopr": None})
    assert build_sopr_7d_series(records)["records"][0]["value"] == pytest.approx(1.0)


def test_sopr_auxiliary_variants_do_not_change_average():
    records = _records("sopr", 7)
    baseline = build_sopr_7d_series(records)["records"][0]["value"]
    for record in records:
        record.update({"a_sopr": 1e9, "sth_sopr": -1e9, "lth_sopr": None})
    assert build_sopr_7d_series(records)["records"][0]["value"] == baseline


def test_sopr_gap_restarts_warmup_and_blocks_non_contiguous_window():
    records = _records("sopr", 14)
    records[7]["timestamp"] += DAY
    for index in range(8, len(records)):
        records[index]["timestamp"] += DAY
    result = build_sopr_7d_series(records)
    assert result["records"][0]["timestamp"] == records[6]["timestamp"]
    assert any(item["reason"] == "non_contiguous_window" for item in result["unavailable_records"])
    assert result["records"][-1]["timestamp"] == records[-1]["timestamp"]


def test_sopr_current_is_last_valid_and_never_nan():
    result = build_sopr_7d_series(_records("sopr", 8))
    assert result["current"]["timestamp"] == result["records"][-1]["timestamp"]
    assert all(math.isfinite(record["value"]) for record in result["records"])


def test_hashrate_conversion_preserves_source_and_precision():
    result = build_hashrate_eh_s_series([{"timestamp": START, "value": 682_900_000_000_000_000_000}])
    record = result["records"][0]
    assert record["value"] == 682.9 and record["source_value"] == 682_900_000_000_000_000_000.0 and record["conversion_scale"] == 1e18


@pytest.mark.parametrize("value", [-1.0, math.inf, -math.inf, math.nan])
def test_hashrate_rejects_invalid_values(value):
    assert build_hashrate_eh_s_series([{"timestamp": START, "value": value}])["status"] == "invalid"


def test_difficulty_conversion_preserves_source_without_mutation():
    source = [{"timestamp": START, "value": 94_600_000_000_000}]
    before = copy.deepcopy(source)
    record = build_difficulty_trillion_series(source)["records"][0]
    assert record["value"] == 94.6 and record["source_value"] == 94_600_000_000_000.0 and source == before


def test_difficulty_rejects_negative_value():
    assert build_difficulty_trillion_series([{"timestamp": START, "value": -1}])["status"] == "invalid"


def test_net_position_daily_deltas_and_current():
    reserve = [{"timestamp": START + index * DAY, "value": value} for index, value in enumerate((100, 110, 105))]
    result = build_miner_net_position_change_series(reserve)
    assert [record["value"] for record in result["records"]] == [10.0, -5.0]
    assert result["unavailable_records"][0]["reason"] == "insufficient_previous_record"
    assert result["current"]["value"] == -5.0 and result["current"]["unit"] == "BTC/day"


def test_net_position_gap_does_not_bridge_missing_day():
    reserve = [{"timestamp": START, "value": 100}, {"timestamp": START + 2 * DAY, "value": 110}, {"timestamp": START + 3 * DAY, "value": 120}]
    result = build_miner_net_position_change_series(reserve)
    assert len(result["records"]) == 1 and result["records"][0]["value"] == 10
    assert result["unavailable_records"][1]["reason"] == "previous_day_missing"


def test_net_position_contains_no_semantic_direction_keys():
    result = build_miner_net_position_change_series(_records("miner_reserve", 3))
    assert {"positive", "negative", "profit", "loss"}.isdisjoint(_keys(result))


def test_reserve_linear_trend_formulas():
    trend = build_reserve_trend_features(_records("miner_reserve", 30))["windows"]["30d"]
    assert trend["slope_btc_per_day"] == pytest.approx(10.0)
    assert trend["r_squared"] == pytest.approx(1.0)
    assert trend["net_change_btc"] == 290.0
    assert trend["percent_change"] == pytest.approx(100 * 290 / 1_000_000)
    assert trend["normalized_slope_percent_per_day"] == pytest.approx(100 * 10 / trend["mean_reserve_btc"])


def test_reserve_constant_trend_has_zero_slope_and_unit_r_squared():
    records = [{"timestamp": START + index * DAY, "value": 100.0} for index in range(30)]
    trend = build_reserve_trend_features(records)["windows"]["30d"]
    assert trend["slope_btc_per_day"] == 0.0 and trend["r_squared"] == 1.0


def test_reserve_regression_uses_real_timestamp_distance():
    records = [{"timestamp": START, "value": 100.0}, {"timestamp": START + 2 * DAY, "value": 120.0}, {"timestamp": START + 5 * DAY, "value": 150.0}]
    assert build_reserve_trend_features(records, window_days=(7,), default_window_days=7)["windows"]["7d"]["slope_btc_per_day"] == pytest.approx(10.0)


@pytest.mark.parametrize(("missing", "complete"), [(2, True), (3, False)])
def test_reserve_window_daily_tolerance(missing, complete):
    records = _records("miner_reserve", 30)
    del records[5:5 + missing]
    window = build_reserve_trend_features(records)["windows"]["30d"]
    assert window["history_complete"] is complete
    assert window["coverage_ratio"] <= 1.0


def test_reserve_less_than_three_observations_has_no_regression():
    window = build_reserve_trend_features(_records("miner_reserve", 2), window_days=(30,), default_window_days=30)["windows"]["30d"]
    assert window["status"] == "unavailable" and window["slope_btc_per_day"] is None


def test_reserve_percent_and_normalized_slope_guard_zero_denominators():
    records = [{"timestamp": START + index * DAY, "value": value} for index, value in enumerate((0.0, -1.0, 1.0))]
    window = build_reserve_trend_features(records, window_days=(3,), default_window_days=3)["windows"]["3d"]
    assert window["percent_change"] is None and window["normalized_slope_percent_per_day"] is None


def test_reserve_trend_has_required_windows_and_default_without_labels(processed):
    trend = processed["features"]["reserve_trend"]
    assert set(trend["windows"]) == {"7d", "30d", "90d"} and trend["default_window_days"] == 30
    assert {"increasing", "stable", "decreasing"}.isdisjoint(_keys(trend))


def test_mpi_and_classification_bases_are_numeric_only(processed):
    mpi = processed["series"]["mpi"]
    basis = processed["features"]["miner_pressure_basis"]
    assert mpi["unit"] == "z_score" and basis["unit"] == "z_score"
    assert basis["change_1d"] == pytest.approx(0.1) and basis["previous"]["timestamp"] + DAY == basis["current"]["timestamp"]
    assert {"pressure", "high_pressure", "low_pressure"}.isdisjoint(_keys(basis))


def test_mpi_gap_removes_previous_and_change():
    source = input_contract()
    source["series"]["mpi"]["records"][-1]["timestamp"] += DAY
    result = process_on_chain_miners(source)["features"]["miner_pressure_basis"]
    assert result["previous"] is None and result["change_1d"] is None


def test_sopr_and_net_position_bases_reference_derived_currents(processed):
    assert processed["features"]["sopr_regime_basis"]["current"] == processed["series"]["sopr_7d"]["current"]
    assert processed["features"]["sopr_regime_basis"]["raw_sopr_current"] == processed["series"]["sopr"]["current"]
    assert processed["features"]["net_position_basis"]["current"] == processed["series"]["miner_net_position_change"]["current"]


def test_quality_ok_when_all_math_is_available(processed):
    assert processed["quality"]["status"] == "ok" and not processed["quality"]["missing_fields"]


def test_input_partial_makes_processing_partial():
    assert process_on_chain_miners(input_contract(input_status="partial"))["quality"]["status"] == "partial"


def test_short_sopr_warmup_makes_processing_partial():
    result = process_on_chain_miners(input_contract(count=6))
    assert result["series"]["sopr_7d"]["status"] == "unavailable" and result["quality"]["status"] == "partial"


@pytest.mark.parametrize(("mutation", "fragment"), [
    (lambda source: source["series"]["hashrate"].update(unit="EH/s"), "incompatible_unit"),
    (lambda source: source["series"]["mpi"]["records"].append(copy.deepcopy(source["series"]["mpi"]["records"][-1])), "duplicate_timestamp"),
    (lambda source: source["series"]["sopr"]["records"].reverse(), "timestamps_not_ascending"),
])
def test_contract_violations_make_processing_invalid(mutation, fragment):
    source = input_contract()
    mutation(source)
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and any(fragment in error for error in result["quality"]["errors"])


@pytest.mark.parametrize(("field", "value", "fragment"), [("family", "prices_ohlcv", "family_must_be"), ("stage", "processing", "stage_must_be"),
                                                            ("mode", "unknown", "mode_must_be")])
def test_invalid_top_level_contract_is_reported(field, value, fragment):
    source = input_contract()
    source[field] = value
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and any(fragment in error for error in result["quality"]["errors"])


def test_missing_core_series_is_invalid():
    source = input_contract()
    del source["series"]["mpi"]
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and "missing_core_series:mpi" in result["quality"]["errors"]


@pytest.mark.parametrize("timestamp", [True, -1, 1.5, "2026-07-27"])
def test_invalid_input_timestamps_are_rejected(timestamp):
    source = input_contract()
    source["series"]["mpi"]["records"][0]["timestamp"] = timestamp
    assert process_on_chain_miners(source)["quality"]["status"] == "invalid"


def test_data_as_of_uses_minimum_required_current_timestamp():
    source = input_contract()
    source["series"]["hashrate"]["records"] = source["series"]["hashrate"]["records"][:-3]
    result = process_on_chain_miners(source)
    assert result["quality"]["data_as_of"] == source["series"]["hashrate"]["records"][-1]["timestamp"]


def test_missing_required_current_makes_data_as_of_null():
    source = input_contract()
    source["series"]["hashrate"]["records"] = []
    result = process_on_chain_miners(source)
    assert result["quality"]["data_as_of"] is None and result["quality"]["status"] == "partial"


def test_unavailable_source_is_not_converted_to_zero():
    source = input_contract()
    source["series"]["difficulty"]["records"] = []
    current = process_on_chain_miners(source)["series"]["difficulty_t"]["current"]
    assert current["status"] == "unavailable" and current["value"] is None


@pytest.mark.parametrize("mode", ["bootstrap", "incremental", "recovery"])
def test_mode_is_preserved_and_complete_history_is_recalculated(mode):
    result = process_on_chain_miners(input_contract(mode=mode))
    assert result["mode"] == mode and len(result["series"]["miner_reserve_btc"]["records"]) == 100


def test_updated_input_timestamp_changes_derived_result():
    source = input_contract()
    baseline = process_on_chain_miners(source)["series"]["miner_net_position_change"]["current"]["value"]
    source["series"]["miner_reserve"]["records"][-1]["value"] += 25
    assert process_on_chain_miners(source)["series"]["miner_net_position_change"]["current"]["value"] == baseline + 25


def test_recovery_history_rebuilds_sopr_and_reserve_delta():
    result = process_on_chain_miners(input_contract(count=7, mode="recovery"))
    assert len(result["series"]["sopr_7d"]["records"]) == 1 and len(result["series"]["miner_net_position_change"]["records"]) == 6


def test_current_snapshot_skips_invalid_trailing_record():
    payload = {"unit": "ratio", "records": [{"timestamp": START, "value": 1.0}, {"timestamp": START + DAY, "value": math.nan}]}
    assert build_current_snapshot(payload)["timestamp"] == START


def test_processing_output_is_strict_json(processed):
    json.dumps(processed, allow_nan=False)


def test_processing_output_contains_only_finite_floats(processed):
    def floats(value):
        if isinstance(value, float):
            yield value
        elif isinstance(value, Mapping):
            for item in value.values():
                yield from floats(item)
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                yield from floats(item)
    assert all(math.isfinite(value) for value in floats(processed))


def test_invalid_mpi_source_blocks_series_basis_and_data_as_of():
    source = input_contract()
    source["series"]["mpi"]["status"] = "invalid"
    result = process_on_chain_miners(source)
    assert result["series"]["mpi"]["status"] == "invalid" and result["series"]["mpi"]["records"] == []
    assert result["features"]["miner_pressure_basis"]["current"]["reason"] == "source_series_invalid"
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


@pytest.mark.parametrize(("source_id", "processing_ids"), [
    ("miner_reserve", ("miner_reserve_btc", "miner_net_position_change")),
    ("sopr", ("sopr", "sopr_7d")),
    ("hashrate", ("hashrate_eh_s",)),
    ("difficulty", ("difficulty_t",)),
    ("mpi", ("mpi",)),
])
def test_each_invalid_core_source_blocks_dependent_series(source_id, processing_ids):
    source = input_contract()
    source["series"][source_id]["status"] = "invalid"
    result = process_on_chain_miners(source)
    assert all(result["series"][metric_id]["status"] == "invalid" for metric_id in processing_ids)
    assert all(f"source_series_invalid:{source_id}" in result["series"][metric_id]["errors"] for metric_id in processing_ids)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


def test_invalid_reserve_blocks_trend_and_net_position_basis():
    source = input_contract()
    source["series"]["miner_reserve"]["status"] = "invalid"
    result = process_on_chain_miners(source)
    assert result["features"]["reserve_trend"]["status"] == "invalid"
    assert result["features"]["net_position_basis"]["current"]["reason"] == "source_series_invalid"


def test_input_quality_invalid_bounds_processing_confidence():
    result = process_on_chain_miners(input_contract(input_status="invalid"))
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert "input_quality_invalid" in result["quality"]["errors"]


def test_input_quality_partial_adds_explicit_warning():
    result = process_on_chain_miners(input_contract(input_status="partial"))
    assert result["quality"]["status"] == "partial" and "input_quality_partial" in result["quality"]["warnings"]


@pytest.mark.parametrize(("field", "message", "expected"), [("warnings", "provider_late", "input_warning:provider_late"),
                                                               ("errors", "provider_error", "input_error:provider_error")])
def test_global_input_messages_are_propagated(field, message, expected):
    source = input_contract(input_status="partial")
    source["quality"][field] = [message, message]
    result = process_on_chain_miners(source)
    target = result["quality"][field]
    assert target.count(expected) == 1


@pytest.mark.parametrize(("field", "message", "expected"), [
    ("warnings", "requested_history_not_fully_covered", "input_series_warning:sopr:requested_history_not_fully_covered"),
    ("errors", "latest_request_failed", "input_series_error:sopr:latest_request_failed"),
])
def test_series_input_messages_are_propagated(field, message, expected):
    source = input_contract()
    source["series"]["sopr"].update(status="partial")
    source["series"]["sopr"][field] = [message, message]
    result = process_on_chain_miners(source)
    assert result["series"]["sopr"][field].count(expected) == 1
    assert any(expected in item for item in result["quality"][field])


@pytest.mark.parametrize("count", [1, 6, 20])
def test_every_partial_quality_has_an_explicit_cause(count):
    quality = process_on_chain_miners(input_contract(count=count))["quality"]
    assert quality["status"] == "partial" and bool(quality["warnings"] or quality["errors"] or quality["missing_fields"])


def test_short_sopr_reports_specific_insufficient_history_warning():
    result = process_on_chain_miners(input_contract(count=6))
    assert "sopr_7d_insufficient_history" in result["series"]["sopr_7d"]["warnings"]


def test_sopr_gap_reports_specific_non_contiguous_warning():
    source = input_contract(count=14)
    for record in source["series"]["sopr"]["records"][7:]:
        record["timestamp"] += DAY
    result = process_on_chain_miners(source)
    assert "sopr_7d_non_contiguous_history" in result["series"]["sopr_7d"]["warnings"]


def test_short_default_reserve_trend_reports_reason_in_global_quality():
    result = process_on_chain_miners(input_contract(count=20))
    assert result["features"]["reserve_trend"]["status"] == "partial"
    assert "reserve_trend_default_window_incomplete" in result["quality"]["warnings"]


def test_regression_zero_x_variance_is_explicitly_invalid():
    records = [{"timestamp": START, "value": float(value)} for value in (1, 2, 3)]
    window = build_reserve_trend_features(records, window_days=(3,), default_window_days=3)["windows"]["3d"]
    assert window["status"] == "invalid" and window["errors"] == ["regression_x_variance_zero"]
    assert window["slope_btc_per_day"] is None and window["r_squared"] is None


def test_two_observation_regression_is_unavailable_with_reason():
    window = build_reserve_trend_features(_records("miner_reserve", 2), window_days=(3,), default_window_days=3)["windows"]["3d"]
    assert window["status"] == "unavailable" and window["warnings"] == ["insufficient_observations_for_regression"]


@pytest.mark.parametrize(("leading", "complete", "status"), [(2, True, "available"), (3, False, "partial")])
def test_reserve_window_counts_leading_missing_days(leading, complete, status):
    records = _records("miner_reserve", 30)[leading:]
    window = build_reserve_trend_features(records)["windows"]["30d"]
    assert window["leading_missing_days"] == leading and window["history_complete"] is complete and window["status"] == status


@pytest.mark.parametrize(("missing", "complete"), [(2, True), (3, False)])
def test_reserve_window_counts_internal_missing_days(missing, complete):
    records = _records("miner_reserve", 30)
    del records[5:5 + missing]
    window = build_reserve_trend_features(records)["windows"]["30d"]
    assert window["internal_missing_days"] == missing and window["history_complete"] is complete


def test_total_missing_days_sums_leading_trailing_and_internal():
    records = _records("miner_reserve", 30)[1:]
    del records[5:7]
    window = build_reserve_trend_features(records)["windows"]["30d"]
    assert window["total_missing_days"] == window["leading_missing_days"] + window["trailing_missing_days"] + window["internal_missing_days"] == 3


def test_reserve_coverage_ratio_is_capped_at_one_with_duplicate_direct_records():
    records = _records("miner_reserve", 30)
    records.extend(copy.deepcopy(records[-1]) for _ in range(3))
    window = build_reserve_trend_features(records)["windows"]["30d"]
    assert window["coverage_ratio"] == 1.0


@pytest.mark.parametrize(("target", "status"), [("series", "unknown"), ("quality", "unknown")])
def test_unknown_status_vocabulary_is_structurally_invalid(target, status):
    source = input_contract()
    if target == "series":
        source["series"]["mpi"]["status"] = status
    else:
        source["quality"]["status"] = status
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None


def test_non_string_input_message_is_structurally_invalid():
    source = input_contract()
    source["quality"]["warnings"] = [{"hidden": "message"}]
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and any("must_be_nonempty_string" in item for item in result["quality"]["errors"])


def test_messages_survive_complete_output_and_classification_keys_remain_absent():
    source = input_contract(input_status="partial")
    source["quality"]["warnings"] = ["global_warning"]
    source["series"]["sopr"].update(status="partial", warnings=["series_warning"])
    result = process_on_chain_miners(source)
    assert "input_warning:global_warning" in result["quality"]["warnings"]
    assert "input_series_warning:sopr:series_warning" in result["series"]["sopr"]["warnings"]
    forbidden = {"signal", "state", "display_signal", "signal_color_token", "display_color_token", "profit", "loss", "increasing", "decreasing",
                 "stable", "high_pressure", "low_pressure", "neutral", "charts", "widgets", "kpis", "selectors", "badges", "screen", "events"}
    assert forbidden.isdisjoint(_keys(result))


NEW_SERIES = {"miners_unspent_supply_btc", "nupl", "miner_outflow_total_btc", "miner_revenue_total_usd",
              "miner_block_reward_revenue_usd", "miner_fee_revenue_usd", "miner_fee_share_ratio"}
NEW_FEATURES = {"miner_outflow_distribution", "reserve_age_context", "miner_revenue_breakdown", "nupl_phase_basis"}


def test_processing_publishes_exact_approved_extension_names(processed):
    assert NEW_SERIES == set(processed["series"]) - {"miner_reserve_btc", "sopr", "sopr_7d", "hashrate_eh_s", "difficulty_t", "miner_net_position_change", "mpi"}
    assert NEW_FEATURES == set(processed["features"]) - {"reserve_trend", "miner_pressure_basis", "sopr_regime_basis", "net_position_basis"}


@pytest.mark.parametrize(("metric_id", "unit"), [("miners_unspent_supply_btc", "BTC"), ("nupl", "ratio"),
                                                    ("miner_outflow_total_btc", "BTC/day"), ("miner_revenue_total_usd", "USD/day"),
                                                    ("miner_block_reward_revenue_usd", "USD/day"), ("miner_fee_revenue_usd", "USD/day"),
                                                    ("miner_fee_share_ratio", "ratio")])
def test_extension_series_units_and_currents(processed, metric_id, unit):
    payload = processed["series"][metric_id]
    assert payload["unit"] == unit and payload["current"]["status"] in {"available", "partial"}


def test_outflow_exact_timestamp_aggregate_shares_ranking_and_top3(processed):
    record = processed["features"]["miner_outflow_distribution"]["records"][-1]
    antpool = next(pool for pool in record["pools"] if pool["miner_symbol"] == "antpool")
    f2pool = next(pool for pool in record["pools"] if pool["miner_symbol"] == "f2pool")
    assert record["aggregate_outflow_total_btc"] == antpool["outflow_total_btc"] + f2pool["outflow_total_btc"]
    assert math.isclose(sum(pool["pool_share_ratio"] for pool in record["pools"]), 1.0)
    assert [pool["rank"] for pool in record["pools"]] == [1, 2]
    assert record["top_pool_symbol"] == "antpool" and record["top1_share_ratio"] == antpool["pool_share_ratio"]
    assert math.isclose(record["top3_share_ratio"], 1.0)
    assert record["aggregate_outflow_total_btc"] != sum(pool["outflow_top10_btc"] for pool in record["pools"])
    assert record["aggregate_outflow_total_btc"] != sum(pool["outflow_mean_btc"] for pool in record["pools"])


def test_outflow_ranking_tie_breaks_by_symbol():
    source = input_contract(count=1)["collections"]["miner_outflow_by_pool"]
    for pool in source["pools"].values():
        pool["records"][0]["outflow_total"] = 10.0
    record = build_miner_outflow_distribution(source)["records"][0]
    assert [pool["miner_symbol"] for pool in record["pools"]] == ["antpool", "f2pool"]


def test_outflow_zero_aggregate_has_null_shares_and_warning():
    source = input_contract(count=1)["collections"]["miner_outflow_by_pool"]
    for pool in source["pools"].values():
        pool["records"][0]["outflow_total"] = 0.0
    record = build_miner_outflow_distribution(source)["records"][0]
    assert all(pool["pool_share_ratio"] is None for pool in record["pools"])
    assert record["top1_share_ratio"] is None and record["top3_share_ratio"] is None
    assert "outflow_share_unavailable_zero_aggregate" in record["warnings"]


def test_outflow_missing_active_pool_is_partial_without_forward_fill():
    source = input_contract(count=3)["collections"]["miner_outflow_by_pool"]
    missing_timestamp = source["pools"]["f2pool"]["records"][1]["timestamp"]
    del source["pools"]["f2pool"]["records"][1]
    distribution = build_miner_outflow_distribution(source)
    record = next(item for item in distribution["records"] if item["timestamp"] == missing_timestamp)
    assert record["status"] == "partial" and record["missing_active_pools"] == ["f2pool"]
    assert [pool["miner_symbol"] for pool in record["pools"]] == ["antpool"]


def test_inactive_pool_history_is_included_but_not_required():
    source = input_contract(count=1)["collections"]["miner_outflow_by_pool"]
    source["pools"]["f2pool"]["active"] = False
    distribution = build_miner_outflow_distribution(source)
    record = distribution["records"][0]
    assert record["status"] == "available" and record["expected_active_pools"] == 1
    assert next(pool for pool in record["pools"] if pool["miner_symbol"] == "f2pool")["active"] is False


def test_outflow_current_uses_collection_data_as_of_exactly():
    source = input_contract(count=3)["collections"]["miner_outflow_by_pool"]
    source["metadata"]["data_as_of"] = source["pools"]["antpool"]["records"][0]["timestamp"]
    distribution = build_miner_outflow_distribution(source)
    assert distribution["current"]["timestamp"] == source["metadata"]["data_as_of"]
    source["metadata"]["data_as_of"] += 123
    missing = build_miner_outflow_distribution(source)
    assert missing["current"]["status"] == "unavailable" and "outflow_current_timestamp_not_available" in missing["warnings"]


@pytest.mark.parametrize("value", [-1.0, math.nan, math.inf])
def test_invalid_outflow_values_make_feature_invalid_and_json_safe(value):
    source = input_contract(count=1)["collections"]["miner_outflow_by_pool"]
    source["pools"]["antpool"]["records"][0]["outflow_total"] = value
    result = build_miner_outflow_distribution(source)
    assert result["status"] == "invalid"
    json.dumps(result, allow_nan=False)


def test_reserve_age_separates_miner_specific_and_bitcoin_network(processed):
    feature = processed["features"]["reserve_age_context"]
    assert feature["miner_specific"]["scope"] == "miner_specific"
    assert feature["miner_specific"]["meaning"] == "coinbase_outputs_never_moved"
    assert feature["network_context"]["scope"] == "bitcoin_network"
    assert feature["network_context"]["is_miner_specific"] is False
    assert len(feature["network_context"]["records"][-1]["bands"]) == 13


def test_utxo_shares_use_native_btc_and_preserve_provider_percent(processed):
    record = processed["features"]["reserve_age_context"]["network_context"]["records"][-1]
    assert math.isclose(sum(band["derived_share_ratio"] for band in record["bands"].values()), 1.0)
    first = record["bands"]["0d_1d"]
    assert first["derived_share_ratio"] == first["native_btc"] / record["network_total_native_btc"]
    assert first["provider_percent"] == 1.0 and first["usd"] == 1000.0


def test_utxo_null_native_does_not_use_usd_and_zero_total_warns():
    source = input_contract(count=1)
    miners = process_on_chain_miners(source)["series"]["miners_unspent_supply_btc"]
    utxo = source["series"]["utxo_age_distribution"]
    utxo["records"][0]["bands"]["0d_1d"]["native_btc"] = None
    result = build_reserve_age_context(miners, utxo)
    assert result["network_context"]["records"][0]["bands"]["0d_1d"]["derived_share_ratio"] is None
    for band in utxo["records"][0]["bands"].values():
        band["native_btc"] = 0.0
    zero = build_reserve_age_context(miners, utxo)
    assert all(band["derived_share_ratio"] is None for band in zero["network_context"]["records"][0]["bands"].values())
    assert "utxo_age_share_unavailable_zero_total" in zero["warnings"]


def test_reserve_age_data_as_of_requires_both_currents(processed):
    feature = processed["features"]["reserve_age_context"]
    expected = min(feature["miner_specific"]["current"]["timestamp"], feature["network_context"]["current"]["timestamp"])
    assert feature["metadata"]["data_as_of"] == expected


def _revenue_sources(total=100.0, block=90.0, provider=0.1, timestamp=START):
    contracts = {"miner_revenue_total_usd": ("USD/day", "glassnode", "revenue_sum"),
                 "miner_block_reward_revenue_usd": ("USD/day", "glassnode", "volume_mined_sum"),
                 "miner_revenue_from_fees": ("provider_native_percentage", "glassnode", "revenue_from_fees")}

    def payload(metric_id, value):
        unit, source_provider, endpoint_id = contracts[metric_id]
        return {"metric_id": metric_id, "status": "available", "unit": unit,
                "records": [{"timestamp": timestamp, "value": value, "unit": unit, "provider": source_provider, "endpoint_id": endpoint_id}],
                "warnings": [], "errors": []}
    return (payload("miner_revenue_total_usd", total), payload("miner_block_reward_revenue_usd", block),
            payload("miner_revenue_from_fees", provider))


@pytest.mark.parametrize(("provider", "scale", "ratio"), [(0.1, "ratio", 0.1), (10.0, "percent", 0.1)])
def test_provider_fee_scale_resolves_closest_candidate(provider, scale, ratio):
    result = build_miner_revenue_breakdown(*_revenue_sources(provider=provider), input_data_as_of=START)
    record = result["records"][0]
    assert record["provider_fee_value"] == provider and record["provider_fee_scale"] == scale and record["provider_fee_ratio"] == ratio


def test_revenue_fee_difference_share_and_percent_are_exact():
    record = build_miner_revenue_breakdown(*_revenue_sources(), input_data_as_of=START)["records"][0]
    assert record["fee_revenue_usd"] == 10.0 and record["derived_fee_share_ratio"] == 0.1 and record["derived_fee_share_percent"] == 10.0


@pytest.mark.parametrize(("total", "block"), [(100.0, 100.0), (100.0, 100.0 + 1e-7)])
def test_revenue_equal_or_float_close_produces_zero_without_negative(total, block):
    record = build_miner_revenue_breakdown(*_revenue_sources(total=total, block=block, provider=0.0), input_data_as_of=START)["records"][0]
    assert record["fee_revenue_usd"] == 0.0


def test_block_reward_above_total_outside_tolerance_invalidates_without_negative_fee():
    result = build_miner_revenue_breakdown(*_revenue_sources(total=100.0, block=101.0), input_data_as_of=START)
    assert result["status"] == "invalid" and not result["records"]
    assert "block_reward_revenue_exceeds_total_revenue" in result["errors"]


def test_zero_total_and_unresolved_provider_scale_are_explicit():
    result = build_miner_revenue_breakdown(*_revenue_sources(total=0.0, block=0.0, provider=101.0), input_data_as_of=START)
    record = result["records"][0]
    assert record["derived_fee_share_ratio"] is None and record["provider_fee_scale"] == "unresolved"
    assert {"fee_share_unavailable_zero_total_revenue", "provider_fee_scale_unresolved"} <= set(record["warnings"])


def test_revenue_alignment_uses_exact_intersection_and_earlier_current():
    total, block, provider = _revenue_sources()
    block["records"][0]["timestamp"] = START - DAY
    result = build_miner_revenue_breakdown(total, block, provider, input_data_as_of=START)
    assert not result["records"] and "revenue_timestamp_alignment_incomplete" in result["warnings"]
    total, block, provider = _revenue_sources(timestamp=START - DAY)
    earlier = build_miner_revenue_breakdown(total, block, provider, input_data_as_of=START)
    assert earlier["current"]["timestamp"] == START - DAY and "revenue_current_before_input_data_as_of" in earlier["warnings"]


def test_nupl_current_previous_and_change_use_exact_calendar_day():
    source = input_contract(count=3)["series"]["nupl"]
    series = build_nupl_series(source)
    basis = build_nupl_phase_basis(series)
    assert basis["current"]["value"] == source["current"]["value"] and basis["current"]["price_usd"] == source["current"]["price_usd"]
    assert basis["previous"]["timestamp"] == basis["current"]["timestamp"] - DAY
    assert math.isclose(basis["change_1d"], basis["current"]["value"] - basis["previous"]["value"])


def test_nupl_gap_never_uses_arbitrary_previous_record():
    source = input_contract(count=3)["series"]["nupl"]
    del source["records"][-2]
    basis = build_nupl_phase_basis(build_nupl_series(source))
    assert basis["previous"]["status"] == "unavailable" and basis["change_1d"] is None
    assert basis["previous"]["reason"] == "previous_calendar_day_unavailable"


def test_nupl_unavailable_input_current_is_not_reconstructed():
    source = input_contract(count=3)["series"]["nupl"]
    source["current"] = {"status": "unavailable", "value": None}
    series = build_nupl_series(source)
    assert series["current"]["status"] == "unavailable" and build_nupl_phase_basis(series)["status"] == "unavailable"


def test_extension_quality_availability_and_data_as_of(processed):
    assert NEW_SERIES | NEW_FEATURES <= set(processed["quality"]["availability"])
    timestamps = [processed["series"][metric_id]["current"]["timestamp"] for metric_id in
                  ("miner_reserve_btc", "sopr_7d", "hashrate_eh_s", "difficulty_t", "miner_net_position_change", "mpi")]
    timestamps.extend(processed["features"][feature_id]["metadata"]["data_as_of"] for feature_id in NEW_FEATURES)
    assert processed["quality"]["data_as_of"] == min(timestamps)


@pytest.mark.parametrize(("container", "metric_id"), [("series", "nupl"), ("series", "utxo_age_distribution"),
                                                         ("collections", "miner_outflow_by_pool")])
def test_partial_extension_source_never_allows_processing_ok(container, metric_id):
    source = input_contract(input_status="partial")
    source[container][metric_id]["status"] = "partial"
    source[container][metric_id]["warnings"] = ["degraded_source"]
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "partial" and result["quality"]["warnings"]


@pytest.mark.parametrize(("container", "metric_id", "field", "expected"), [
    ("series", "nupl", "warnings", "input_series_warning:nupl:nupl_warning"),
    ("series", "nupl", "errors", "input_series_error:nupl:nupl_error"),
    ("collections", "miner_outflow_by_pool", "warnings", "input_collection_warning:miner_outflow_by_pool:pool_warning"),
    ("collections", "miner_outflow_by_pool", "errors", "input_collection_error:miner_outflow_by_pool:pool_error"),
])
def test_extension_input_messages_are_propagated(container, metric_id, field, expected):
    source = input_contract(input_status="partial")
    source[container][metric_id][field] = [expected.rsplit(":", 1)[-1]]
    result = process_on_chain_miners(source)
    target = result["quality"]["errors" if field == "errors" else "warnings"]
    assert expected in target


def test_extension_semantic_and_presentation_fields_are_absent(processed):
    forbidden = {"widgets", "charts", "screen", "contract", "events", "display_value", "display_color_token", "classification_label",
                 "nupl_phase", "outflow_state", "revenue_regime", "reserve_age_state", "market_signal", "bullish", "bearish",
                 "young_supply", "old_supply", "reserve_age_score", "miner_age_distribution"}
    assert forbidden.isdisjoint(_keys(processed))


def test_extension_nested_mappings_are_new_objects():
    source = input_contract(count=2)
    result = process_on_chain_miners(source)
    output_pool = result["features"]["miner_outflow_distribution"]["records"][0]["pools"][0]
    output_band = result["features"]["reserve_age_context"]["network_context"]["records"][0]["bands"]["0d_1d"]
    assert all(output_pool is not pool for pool in source["collections"]["miner_outflow_by_pool"]["pools"].values())
    assert output_band is not source["series"]["utxo_age_distribution"]["records"][0]["bands"]["0d_1d"]


def test_invalid_non_json_extension_output_is_sanitized_and_serializable():
    source = input_contract()
    source["context"]["data_mode"] = object()
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and result["context"]["data_mode"] is None
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_no_active_outflow_pools_blocks_current_data_as_of_and_aggregate_series():
    source = input_contract(count=2)["collections"]["miner_outflow_by_pool"]
    for pool in source["pools"].values():
        pool["active"] = False
    feature = build_miner_outflow_distribution(source)
    series = build_miner_outflow_total_series(feature)
    assert feature["status"] == "unavailable" and feature["current"] == {"status": "unavailable", "value": None, "reason": "no_active_outflow_pools"}
    assert feature["metadata"]["data_as_of"] is None and "no_active_outflow_pools" in feature["warnings"]
    assert series["status"] == "unavailable" and series["records"] == [] and series["current"]["status"] == "unavailable"


@pytest.mark.parametrize(("symbol", "active"), [("antpool", True), ("f2pool", False)])
def test_invalid_pool_is_never_consumed_and_invalidates_feature(symbol, active):
    source = input_contract(count=2)["collections"]["miner_outflow_by_pool"]
    source["pools"][symbol]["active"] = active
    source["pools"][symbol]["status"] = "invalid"
    feature = build_miner_outflow_distribution(source)
    assert feature["status"] == "invalid" and feature["records"] == [] and feature["current"]["status"] == "unavailable"
    assert f"source_pool_invalid:{symbol}" in feature["errors"] and feature["metadata"]["data_as_of"] is None


@pytest.mark.parametrize(("pool_status", "expected"), [("partial", "partial"), ("unavailable", "partial")])
def test_degraded_active_pool_propagates_status_and_warning(pool_status, expected):
    source = input_contract(count=2)["collections"]["miner_outflow_by_pool"]
    source["pools"]["f2pool"]["status"] = pool_status
    feature = build_miner_outflow_distribution(source)
    assert feature["status"] == expected
    assert f"source_pool_{pool_status}:f2pool" in feature["warnings"]


def test_miners_unspent_current_unavailable_keeps_history_without_reconstruction():
    source = input_contract(count=2)["series"]["miners_unspent_supply"]
    source["current"] = {"status": "unavailable", "value": None}
    result = build_miners_unspent_supply_series(source)
    assert result["status"] == "partial" and result["records"] and result["current"]["status"] == "unavailable"
    assert "input_current_unavailable:miners_unspent_supply" in result["warnings"]


def test_miners_unspent_current_mismatch_is_invalid():
    source = input_contract(count=2)["series"]["miners_unspent_supply"]
    source["current"]["value"] += 1
    result = build_miners_unspent_supply_series(source)
    assert result["status"] == "invalid" and result["current"]["status"] == "unavailable"
    assert "input_current_not_in_valid_records" in result["errors"]


def test_utxo_current_unavailable_keeps_history_but_blocks_reserve_age_data_as_of():
    source = input_contract(count=2)
    miners = build_miners_unspent_supply_series(source["series"]["miners_unspent_supply"])
    source["series"]["utxo_age_distribution"]["current"] = {"status": "unavailable"}
    feature = build_reserve_age_context(miners, source["series"]["utxo_age_distribution"])
    assert feature["status"] == "partial" and feature["network_context"]["records"]
    assert feature["network_context"]["current"]["status"] == "unavailable" and feature["metadata"]["data_as_of"] is None


def test_utxo_current_missing_timestamp_invalidates_network_context():
    source = input_contract(count=2)
    miners = build_miners_unspent_supply_series(source["series"]["miners_unspent_supply"])
    source["series"]["utxo_age_distribution"]["current"] = {"status": "available", "timestamp": START + 99 * DAY}
    feature = build_reserve_age_context(miners, source["series"]["utxo_age_distribution"])
    assert feature["status"] == "invalid" and feature["network_context"]["records"] == []
    assert "utxo_input_current_not_in_valid_records" in feature["errors"] and feature["metadata"]["data_as_of"] is None


def test_utxo_exact_input_current_is_copied():
    source = input_contract(count=2)
    miners = build_miners_unspent_supply_series(source["series"]["miners_unspent_supply"])
    feature = build_reserve_age_context(miners, source["series"]["utxo_age_distribution"])
    current = feature["network_context"]["current"]
    assert current["status"] == "available" and current["timestamp"] == source["series"]["utxo_age_distribution"]["current"]["timestamp"]


def test_derived_revenue_series_share_feature_current_timestamp():
    source = input_contract(count=3)
    source["quality"]["data_as_of"] = source["series"]["miner_revenue_total_usd"]["records"][1]["timestamp"]
    result = process_on_chain_miners(source)
    timestamp = result["features"]["miner_revenue_breakdown"]["current"]["timestamp"]
    assert result["series"]["miner_fee_revenue_usd"]["current"]["timestamp"] == timestamp
    assert result["series"]["miner_fee_share_ratio"]["current"]["timestamp"] == timestamp
    assert timestamp != source["series"]["miner_revenue_total_usd"]["records"][2]["timestamp"]


def test_unavailable_revenue_feature_leaves_derived_currents_unavailable():
    source = input_contract(count=2)
    source["series"]["miner_revenue_from_fees"]["status"] = "unavailable"
    source["series"]["miner_revenue_from_fees"]["records"] = []
    result = process_on_chain_miners(source)
    assert result["features"]["miner_revenue_breakdown"]["current"]["status"] == "unavailable"
    assert all(result["series"][metric_id]["current"]["status"] == "unavailable"
               for metric_id in ("miner_fee_revenue_usd", "miner_fee_share_ratio"))


@pytest.mark.parametrize(("record_price", "current_price", "accepted"), [(100.0, 100.0, True), (100.0, 101.0, False), (None, None, True), (None, 100.0, False)])
def test_nupl_current_requires_matching_price(record_price, current_price, accepted):
    source = input_contract(count=2)["series"]["nupl"]
    source["records"][-1]["price_usd"] = record_price
    source["current"]["price_usd"] = current_price
    series = build_nupl_series(source)
    basis = build_nupl_phase_basis(series)
    assert (series["status"] == "available") is accepted
    if not accepted:
        assert series["current"]["status"] == "unavailable" and "nupl_current_price_mismatch" in series["errors"]
        assert basis["status"] == "invalid" and basis["previous"]["status"] == "unavailable" and basis["change_1d"] is None


@pytest.mark.parametrize("metric_id", ["miners_unspent_supply", "utxo_age_distribution", "miner_revenue_total_usd",
                                        "miner_block_reward_revenue_usd", "miner_revenue_from_fees", "nupl"])
@pytest.mark.parametrize("defect", ["descending", "duplicate"])
def test_extension_source_order_and_duplicates_are_structurally_invalid(metric_id, defect):
    source = input_contract(count=3)
    records = source["series"][metric_id]["records"]
    if defect == "descending":
        records[0], records[1] = records[1], records[0]
    else:
        records[1]["timestamp"] = records[0]["timestamp"]
    result = process_on_chain_miners(source)
    expected = f"source_timestamps_not_strictly_ascending:{metric_id}" if defect == "descending" else f"source_duplicate_timestamp:{metric_id}:{records[0]['timestamp']}"
    assert result["quality"]["status"] == "invalid" and expected in result["quality"]["errors"]


@pytest.mark.parametrize(("field", "value"), [("provider", "wrong"), ("endpoint_id", "wrong"), ("unit", "ratio")])
def test_revenue_from_fees_contract_fields_are_required(field, value):
    source = input_contract(count=2)
    source["series"]["miner_revenue_from_fees"]["records"][0][field] = value
    result = process_on_chain_miners(source)
    feature = result["features"]["miner_revenue_breakdown"]
    assert feature["status"] == "invalid" and feature["records"] == [] and feature["current"]["status"] == "unavailable"
    assert f"incompatible_revenue_from_fees_contract:{field}" in feature["errors"]


@pytest.mark.parametrize(("field", "value"), [("timestamp", 1.5), ("timestamp", -1), ("value", -1.0), ("value", math.nan)])
def test_revenue_from_fees_invalid_record_blocks_all_derived_output(field, value):
    source = input_contract(count=2)
    source["series"]["miner_revenue_from_fees"]["records"][0][field] = value
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert result["features"]["miner_revenue_breakdown"]["records"] == []
    assert all(result["series"][metric_id]["status"] == "invalid" and result["series"][metric_id]["records"] == []
               for metric_id in ("miner_fee_revenue_usd", "miner_fee_share_ratio"))
    json.dumps(result, ensure_ascii=False, allow_nan=False)


@pytest.mark.parametrize(("metric_id", "value"), [("miner_revenue_total_usd", math.nan), ("miner_revenue_total_usd", -1.0),
                                                     ("miner_block_reward_revenue_usd", math.inf)])
def test_any_invalid_revenue_record_clears_feature_and_derived_series(metric_id, value):
    source = input_contract(count=3)
    source["series"][metric_id]["records"][1]["value"] = value
    result = process_on_chain_miners(source)
    assert result["features"]["miner_revenue_breakdown"]["status"] == "invalid"
    assert result["features"]["miner_revenue_breakdown"]["records"] == []
    assert all(result["series"][derived]["records"] == [] for derived in ("miner_fee_revenue_usd", "miner_fee_share_ratio"))


@pytest.mark.parametrize("location", ["context", "series", "pools", "bands"])
def test_non_string_keys_return_invalid_serializable_contract_with_path(location):
    source = input_contract(count=2)
    if location == "context":
        source["context"][1] = "bad"
    elif location == "series":
        source["series"][1] = {}
    elif location == "pools":
        source["collections"]["miner_outflow_by_pool"]["pools"][1] = {}
    else:
        source["series"]["utxo_age_distribution"]["records"][0]["bands"][1] = {}
    result = process_on_chain_miners(source)
    assert result["quality"]["status"] == "invalid"
    assert any(error.startswith("non_string_input_key:input.") for error in result["quality"]["errors"])
    json.dumps(result, ensure_ascii=False, allow_nan=False)


def test_public_fallback_returns_complete_invalid_contract(monkeypatch):
    source = input_contract(count=2)

    def fail(_self):
        raise TypeError("offensive object must not be copied")

    monkeypatch.setattr(OnChainMinersProcessor, "run", fail)
    result = process_on_chain_miners(source)
    assert result["family"] == "on_chain_miners" and result["stage"] == "processing"
    assert result["quality"]["status"] == "invalid" and result["quality"]["data_as_of"] is None
    assert result["quality"]["errors"] == ["processing_contract_build_failed:TypeError"]
    assert NEW_SERIES <= set(result["series"]) and NEW_FEATURES <= set(result["features"])
    json.dumps(result, ensure_ascii=False, allow_nan=False)
