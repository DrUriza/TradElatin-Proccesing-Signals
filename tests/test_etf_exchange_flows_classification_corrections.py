"""Causal timestamp corrections for ETF exchange-flow Classification."""
from copy import deepcopy
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path

from etf_exchange_flows_classification_helpers import NOW, PARAMETERS, cloned_processing, feature
from processing_signals.classification.etf_exchange_flows import (
    classify_etf_exchange_flows,
    classify_etf_flow_direction,
)


def run(processing, generated_at=NOW):
    return classify_etf_exchange_flows(processing_contract=processing, generated_at=generated_at)


def assert_temporal_invalid(item):
    assert (item["state"], item["status"], item["reason"], item["data_as_of"]) == (
        None, "invalid", "processing_timestamp_inconsistent", None)
    assert item["warnings"] == ["processing_timestamp_inconsistent"]


def test_etf_cc01_cc03_direction_after_equal_and_before_anchor():
    processing = cloned_processing()
    processing["data_as_of"] = NOW - 100
    result = run(processing)["classifications"]["etf_flow_direction"]["1d"]
    assert_temporal_invalid(result)
    assert result["evidence"] == {"source_data_as_of": NOW, "processing_data_as_of": NOW - 100}
    for timestamp in (NOW, NOW - 1):
        processing = cloned_processing()
        processing["features"]["etf"]["period_flow_usd"]["1d"]["data_as_of"] = timestamp
        item = run(processing)["classifications"]["etf_flow_direction"]["1d"]
        assert item["status"] == "available" and item["data_as_of"] == timestamp


def test_etf_cc04_cc07_all_simple_classifiers_reject_later_anchor():
    cases = (
        ("premium_discount", "gbtc_latest", "gbtc_premium_regime"),
        ("pressure", "flow_24h", "exchange_pressure_regime"),
        ("exchange_flows", "netflow_24h_reported", "exchange_netflow_regime"),
    )
    for group, name, classification in cases:
        processing = cloned_processing()
        processing["data_as_of"] = NOW - 1
        assert_temporal_invalid(run(processing)["classifications"][classification])
    processing = cloned_processing()
    processing["data_as_of"] = NOW - 1
    assert_temporal_invalid(run(processing)["classifications"]["aum_reconciliation_state"])


def test_etf_cc08_persistence_propagates_precise_reason():
    processing = cloned_processing()
    processing["features"]["etf"]["period_flow_usd"]["7d"]["data_as_of"] = NOW + 1
    item = run(processing, generated_at=NOW + 100)["classifications"]["etf_flow_persistence"]
    assert_temporal_invalid(item)


def test_etf_cc09_cc11_composite_and_confidence_propagate_from_each_pillar():
    for path in (("etf", "period_flow_usd", "1d"), ("pressure", "flow_24h")):
        processing = cloned_processing()
        target = processing["features"]
        for part in path:
            target = target[part]
        target["data_as_of"] = NOW + 1
        classifications = run(processing, generated_at=NOW + 100)["classifications"]
        assert_temporal_invalid(classifications["composite_capital_flow_regime"])
        assert_temporal_invalid(classifications["data_confidence"])


def test_etf_cc12_every_valid_local_wrapper_respects_processing_anchor():
    processing = cloned_processing()
    for index, name in enumerate(("1d", "7d", "30d", "90d"), 1):
        processing["features"]["etf"]["period_flow_usd"][name]["data_as_of"] = NOW - index
    processing["features"]["premium_discount"]["gbtc_latest"]["data_as_of"] = NOW - 5
    processing["features"]["pressure"]["flow_24h"]["data_as_of"] = NOW - 6
    processing["features"]["exchange_flows"]["netflow_24h_reported"]["data_as_of"] = NOW - 7
    processing["features"]["provider_reconciliation"]["aum"]["difference_percent"]["data_as_of"] = NOW - 8
    output = run(processing)
    wrappers = list(output["classifications"]["etf_flow_direction"].values()) + [
        item for name, item in output["classifications"].items() if name != "etf_flow_direction"]
    assert all(item["data_as_of"] is None or item["data_as_of"] <= processing["data_as_of"] for item in wrappers)


def test_etf_cc13_generated_at_does_not_authorize_root_inconsistency():
    processing = cloned_processing()
    processing["data_as_of"] = NOW - 1
    first = run(processing, generated_at=NOW)
    second = run(processing, generated_at=NOW + 10_000)
    assert_temporal_invalid(first["classifications"]["etf_flow_direction"]["1d"])
    assert first["classifications"] == second["classifications"]


def test_etf_cc14_cc15_bool_and_nonfinite_timestamp_rejected_by_helper_path():
    for timestamp in (True, math.inf):
        item = classify_etf_flow_direction(feature(1, data_as_of=timestamp), range_id="1d",
            generated_timestamp=NOW, parameters=PARAMETERS, processing_data_as_of=NOW)
        assert_temporal_invalid(item)
        if timestamp is True:
            assert item["evidence"]["source_data_as_of"] is True
        else:
            assert item["evidence"]["source_data_as_of_type"] == "float"


def test_etf_cc16_optional_later_does_not_invalidate_required():
    processing = cloned_processing()
    processing["features"]["premium_discount"]["gbtc_latest"]["data_as_of"] = NOW + 1
    output = run(processing, generated_at=NOW + 100)
    assert_temporal_invalid(output["classifications"]["gbtc_premium_regime"])
    assert output["quality"]["status"] == "ok"
    assert "gbtc_premium_regime" in output["quality"]["invalid"]


def test_etf_cc17_required_later_makes_quality_partial_while_pressure_survives():
    processing = cloned_processing()
    processing["features"]["etf"]["period_flow_usd"]["1d"]["data_as_of"] = NOW + 1
    output = run(processing, generated_at=NOW + 100)
    assert output["quality"]["status"] == "partial"
    assert "etf_flow_direction.1d" in output["quality"]["invalid"]
    assert output["classifications"]["exchange_pressure_regime"]["status"] == "available"


def test_etf_cc18_no_required_usable_makes_quality_invalid():
    processing = cloned_processing()
    processing["features"]["etf"]["period_flow_usd"]["1d"]["data_as_of"] = NOW + 1
    processing["features"]["pressure"]["flow_24h"]["data_as_of"] = NOW + 1
    output = run(processing, generated_at=NOW + 100)
    assert output["quality"]["status"] == "invalid"
    assert set(output["quality"]["invalid"]) >= {"etf_flow_direction.1d", "exchange_pressure_regime",
                                                   "composite_capital_flow_regime", "data_confidence"}


def test_etf_cc19_cc20_strict_json_and_immutability():
    processing = cloned_processing()
    processing["features"]["pressure"]["flow_24h"]["data_as_of"] = NOW + 1
    before = deepcopy(processing)
    first, second = run(processing, NOW + 100), run(processing, NOW + 100)
    json.dumps(first, ensure_ascii=False, allow_nan=False)
    assert processing == before and first == second
    first["classifications"]["exchange_pressure_regime"]["warnings"].append("mutated")
    assert second["classifications"]["exchange_pressure_regime"]["warnings"] == [
        "processing_timestamp_inconsistent"]


def test_etf_cc21_cc23_boundaries_persistence_and_composite_regressions():
    processing = cloned_processing()
    result = run(processing)["classifications"]
    assert result["exchange_pressure_regime"]["state"] == "strong_exchange_inflow"
    assert result["gbtc_premium_regime"]["state"] == "premium"
    assert result["etf_flow_persistence"]["state"] == "persistent_outflow"
    assert result["composite_capital_flow_regime"]["state"] == "distribution"


def test_etf_cc24_cc25_frozen_hashes_and_boundaries():
    root = Path(__file__).parents[1]
    expected = {
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_extract.py": "2E98421B5F7502877552E3DBCA6EEF3774CCD9C4476325AAE61D2B47B9A0C8CC",
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_preprocessing.py": "8353C2AE7227EDBB23D3F70B00363975FC6B44F6639AAFE47F5743E3DE1953BE",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_feature_builder.py": "832FD3A63D7A0C0A3E56474948587B468225ECE06E250869E0C2B802334BCD72",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_processor.py": "D8590C91815936074F837041DC8D354646C854EA9EDB754863DCAEAF850B014E",
    }
    assert {path: hashlib.sha256((root / path).read_bytes()).hexdigest().upper() for path in expected} == expected


def test_etf_cc26_cc31_all_incompatible_timestamp_types_are_rejected():
    incompatible = (
        "2025-02-19T21:20:00+00:00", "1740000000", 1740000000.0, True,
        Decimal("1740000000"), {"timestamp": NOW}, [NOW],
    )
    for timestamp in incompatible:
        item = classify_etf_flow_direction(feature(1, data_as_of=timestamp), range_id="1d",
            generated_timestamp=NOW, parameters=PARAMETERS, processing_data_as_of=NOW)
        assert_temporal_invalid(item)
        assert item["evidence"]["processing_data_as_of"] == NOW
        json.dumps(item, allow_nan=False)


def test_etf_cc32_cc35_strict_int_boundaries_and_generated_at_independence():
    for timestamp in (NOW, NOW - 1):
        item = classify_etf_flow_direction(feature(1, data_as_of=timestamp), range_id="1d",
            generated_timestamp=NOW + 10_000, parameters=PARAMETERS, processing_data_as_of=NOW)
        assert (item["state"], item["status"], item["data_as_of"]) == ("inflow", "available", timestamp)
    later = classify_etf_flow_direction(feature(1, data_as_of=NOW + 1), range_id="1d",
        generated_timestamp=NOW + 10_000, parameters=PARAMETERS, processing_data_as_of=NOW)
    assert_temporal_invalid(later)


def test_etf_cc36_cc38_derived_classifications_propagate_string_timestamp():
    for path in (("etf", "period_flow_usd", "1d"), ("pressure", "flow_24h")):
        processing = cloned_processing()
        target = processing["features"]
        for part in path:
            target = target[part]
        target["data_as_of"] = "2025-02-19T21:20:00+00:00"
        classifications = run(processing)["classifications"]
        if path[0] == "etf":
            assert_temporal_invalid(classifications["etf_flow_persistence"])
        assert_temporal_invalid(classifications["composite_capital_flow_regime"])
        assert_temporal_invalid(classifications["data_confidence"])


def test_etf_cc39_cc40_strict_json_and_frozen_hashes_with_incompatible_type():
    processing = cloned_processing()
    processing["features"]["pressure"]["flow_24h"]["data_as_of"] = Decimal("1740000000")
    item = classify_etf_flow_direction(feature(1, data_as_of=Decimal("1740000000")), range_id="1d",
        generated_timestamp=NOW, parameters=PARAMETERS, processing_data_as_of=NOW)
    json.dumps(item, allow_nan=False)
    assert item["evidence"] == {"source_data_as_of_type": "Decimal", "processing_data_as_of": NOW}
    root = Path(__file__).parents[1]
    expected = {
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_extract.py": "2E98421B5F7502877552E3DBCA6EEF3774CCD9C4476325AAE61D2B47B9A0C8CC",
        "src/processing_signals/input/etf_exchange_flows/etf_exchange_flows_data_raw_preprocessing.py": "8353C2AE7227EDBB23D3F70B00363975FC6B44F6639AAFE47F5743E3DE1953BE",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_feature_builder.py": "832FD3A63D7A0C0A3E56474948587B468225ECE06E250869E0C2B802334BCD72",
        "src/processing_signals/processing/etf_exchange_flows/etf_exchange_flows_processor.py": "D8590C91815936074F837041DC8D354646C854EA9EDB754863DCAEAF850B014E",
    }
    assert {path: hashlib.sha256((root / path).read_bytes()).hexdigest().upper() for path in expected} == expected
