from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
import runpy

import pytest

import processing_signals.main.open_interest_and_funding.open_interest_and_funding_vertical as vertical
from processing_signals.main.open_interest_and_funding import (
    build_open_interest_and_funding_screen,
    run_open_interest_and_funding_vertical,
)


PROCESSING_TEST = Path(__file__).with_name("test_open_interest_and_funding_processing_vertical.py")
INPUT_TEST = Path(__file__).with_name("test_open_interest_and_funding_input_vertical.py")
SOURCE = Path(vertical.__file__)


@pytest.fixture(scope="session")
def input_contract() -> dict:
    return runpy.run_path(str(PROCESSING_TEST))["_input"]()


@pytest.fixture(scope="session")
def input_helpers() -> dict:
    return runpy.run_path(str(INPUT_TEST))


@pytest.fixture(scope="session")
def screen(input_contract) -> dict:
    return build_open_interest_and_funding_screen(input_contract)


def test_public_functional_api_and_no_oo_facade():
    assert callable(build_open_interest_and_funding_screen)
    assert callable(run_open_interest_and_funding_vertical)
    assert not hasattr(vertical, "OpenInterestAndFundingVertical")


def test_valid_input_returns_only_screen(input_contract):
    result = build_open_interest_and_funding_screen(input_contract)
    assert tuple(result) == vertical.SCREEN_ROOT
    assert (result["family"], result["stage"], result["version"]) == (
        vertical.FAMILY, "screen_contract", "0.1")
    assert not ({"input", "processing", "classification", "screen"} <= set(result))


@pytest.mark.parametrize("value", [None, [], "x", 1, True])
def test_input_root_must_be_mapping(value):
    with pytest.raises(ValueError, match="^vertical_input_invalid:root$"):
        build_open_interest_and_funding_screen(value)


@pytest.mark.parametrize(("field", "value", "reason"), [
    ("family", "prices_ohlcv", "family"), ("stage", "raw_input", "stage"),
    ("mode", "other", "mode"), ("context", [], "context"),
])
def test_input_boundary_identity(input_contract, field, value, reason):
    candidate = copy.deepcopy(input_contract)
    candidate[field] = value
    with pytest.raises(ValueError, match=rf"^vertical_input_invalid:{reason}$"):
        build_open_interest_and_funding_screen(candidate)


def test_default_and_all_selected_timeframes(input_contract):
    default = build_open_interest_and_funding_screen(input_contract)
    assert default["timeframe_selector"]["selected_timeframe"] == "1h"
    for timeframe in ("1m", "5m", "15m", "1h", "4h", "1d"):
        result = build_open_interest_and_funding_screen(input_contract, selected_timeframe=timeframe)
        assert result["timeframe_selector"]["selected_timeframe"] == timeframe


@pytest.mark.parametrize("value", [None, True, 1, 1.0, "", "2h"])
def test_invalid_selected_timeframe(input_contract, value):
    with pytest.raises(ValueError, match="^vertical_input_invalid:selected_timeframe$"):
        build_open_interest_and_funding_screen(input_contract, selected_timeframe=value)


@pytest.mark.parametrize("value", [None, 0, 1, "false", []])
def test_debug_flag_is_exact_bool(input_contract, value):
    with pytest.raises(ValueError, match="^vertical_input_invalid:include_debug_bundle$"):
        build_open_interest_and_funding_screen(input_contract, include_debug_bundle=value)


def test_call_graph_once_order_bundle_and_timeframe(monkeypatch, input_contract, screen):
    calls = []
    processing = vertical.process_open_interest_and_funding(copy.deepcopy(input_contract))
    classification = vertical.classify_open_interest_and_funding(copy.deepcopy(processing))

    def process(value):
        calls.append(("processing", value))
        return copy.deepcopy(processing)

    def classify(value):
        calls.append(("classification", value))
        return copy.deepcopy(classification)

    def build(bundle, *, selected_timeframe):
        calls.append(("builder", bundle, selected_timeframe))
        return copy.deepcopy(screen)

    monkeypatch.setattr(vertical, "process_open_interest_and_funding", process)
    monkeypatch.setattr(vertical, "classify_open_interest_and_funding", classify)
    monkeypatch.setattr(vertical, "build_open_interest_and_funding_contract", build)
    vertical.build_open_interest_and_funding_screen(input_contract, selected_timeframe="4h")
    assert [item[0] for item in calls] == ["processing", "classification", "builder"]
    assert set(calls[2][1]) == {"processing", "classification"}
    assert calls[2][2] == "4h"


def _patch_stage(monkeypatch, stage, value):
    name = {"processing": "process_open_interest_and_funding",
            "classification": "classify_open_interest_and_funding",
            "screen": "build_open_interest_and_funding_contract"}[stage]
    monkeypatch.setattr(vertical, name, lambda *args, **kwargs: copy.deepcopy(value))


@pytest.mark.parametrize("stage", ["processing", "classification", "screen"])
def test_stage_non_mapping(monkeypatch, input_contract, stage):
    _patch_stage(monkeypatch, stage, [])
    with pytest.raises(ValueError, match=rf"^vertical_output_invalid:{stage}$"):
        build_open_interest_and_funding_screen(input_contract)


@pytest.mark.parametrize("stage", ["processing", "classification", "screen"])
def test_stage_identity_version_mode_and_context(monkeypatch, input_contract, screen, stage):
    processing = vertical.process_open_interest_and_funding(input_contract)
    classification = vertical.classify_open_interest_and_funding(processing)
    base = {"processing": processing, "classification": classification, "screen": screen}[stage]
    for field, value, error in (
        ("family", "wrong", f"vertical_output_invalid:{stage}"),
        ("stage", "wrong", f"vertical_stage_mismatch:{stage}"),
        ("version", "9", f"vertical_output_invalid:{stage}"),
        ("mode", "recovery" if input_contract["mode"] != "recovery" else "bootstrap",
         f"vertical_mode_mismatch:{stage}"),
        ("context", {"wrong": True}, f"vertical_context_mismatch:{stage}"),
    ):
        candidate = copy.deepcopy(base)
        candidate[field] = value
        _patch_stage(monkeypatch, stage, candidate)
        with pytest.raises(ValueError, match=rf"^{error}$"):
            build_open_interest_and_funding_screen(input_contract)
        monkeypatch.undo()


def test_screen_root_must_be_exact(monkeypatch, input_contract, screen):
    candidate = copy.deepcopy(screen)
    candidate["extra"] = True
    _patch_stage(monkeypatch, "screen", candidate)
    with pytest.raises(ValueError, match="^vertical_output_invalid:screen$"):
        build_open_interest_and_funding_screen(input_contract)


def test_debug_exact_order_json_and_deep_independence(input_contract):
    before = copy.deepcopy(input_contract)
    debug = build_open_interest_and_funding_screen(input_contract, include_debug_bundle=True)
    assert tuple(debug) == ("input", "processing", "classification", "screen")
    json.dumps(debug, ensure_ascii=False, allow_nan=False, sort_keys=False)
    debug["input"]["context"]["asset"] = "MUTATED"
    assert debug["processing"]["context"]["asset"] == "BTC"
    assert debug["classification"]["context"]["asset"] == "BTC"
    assert debug["screen"]["context"]["asset"] == "BTC"
    assert input_contract == before


def test_output_input_immutability_and_determinism(input_contract):
    source = copy.deepcopy(input_contract)
    before = copy.deepcopy(source)
    first = build_open_interest_and_funding_screen(source)
    second = build_open_interest_and_funding_screen(copy.deepcopy(source))
    assert first == second and source == before
    first["context"]["asset"] = "MUTATED"
    assert source == before and second["context"]["asset"] == "BTC"


def test_quality_is_builder_quality_and_invalid_is_returnable(monkeypatch, input_contract, screen):
    candidate = copy.deepcopy(screen)
    candidate["quality"]["status"] = "invalid"
    _patch_stage(monkeypatch, "screen", candidate)
    result = build_open_interest_and_funding_screen(input_contract)
    assert result["quality"] == candidate["quality"] and "vertical_quality" not in result


def _runtime_args(input_helpers, **extra):
    return {"mode": "bootstrap", "fetcher": input_helpers["_fetcher"],
            "reference_timestamp": input_helpers["NOW"], "execution_timestamp": input_helpers["NOW"],
            "data_mode": "synthetic", "is_demo": True, **extra}


def test_runtime_bootstrap_end_to_end(input_helpers):
    result = run_open_interest_and_funding_vertical(**_runtime_args(input_helpers))
    assert result["mode"] == "bootstrap" and result["is_demo"] is True


def test_runtime_incremental_and_recovery_end_to_end(input_helpers):
    initial = vertical.run_open_interest_and_funding_input(
        fetcher=input_helpers["_fetcher"], reference_timestamp=input_helpers["NOW"],
        requested_mode="bootstrap", data_mode="synthetic", is_demo=True,
        execution_timestamp=input_helpers["NOW"],
    )
    incremental = run_open_interest_and_funding_vertical(**_runtime_args(
        input_helpers, mode="incremental", input_state=initial,
        reference_timestamp=input_helpers["NOW"] + 3600,
        execution_timestamp=input_helpers["NOW"] + 3600,
    ))
    request = {"metric_id": "open_interest_ohlc", "timeframe": "1h",
               "start_timestamp": input_helpers["NOW"] - 7200,
               "end_timestamp": input_helpers["NOW"] - 3600}
    recovery = run_open_interest_and_funding_vertical(**_runtime_args(
        input_helpers, mode="recovery", input_state=initial, recovery_requests=[request],
    ))
    assert incremental["mode"] == "incremental" and recovery["mode"] == "recovery"


@pytest.mark.parametrize(("mode", "state", "requests", "reason"), [
    ("bootstrap", {}, None, "input_state"), ("bootstrap", None, [], "recovery_requests"),
    ("incremental", None, None, "input_state"), ("incremental", {}, [], "recovery_requests"),
    ("recovery", None, [{}], "input_state"), ("recovery", {}, None, "recovery_requests"),
    ("recovery", {}, [], "recovery_requests"), ("recovery", {}, "x", "recovery_requests"),
    ("recovery", {}, [1], "recovery_requests"),
])
def test_runtime_mode_combinations(input_helpers, mode, state, requests, reason):
    with pytest.raises(ValueError, match=rf"^vertical_input_invalid:{reason}$"):
        run_open_interest_and_funding_vertical(**_runtime_args(
            input_helpers, mode=mode, input_state=state, recovery_requests=requests))


@pytest.mark.parametrize("field", ["reference_timestamp", "execution_timestamp"])
@pytest.mark.parametrize("value", [True, -1, 1.5, "1", None])
def test_runtime_timestamps_are_exact_nonnegative_int(input_helpers, field, value):
    with pytest.raises(ValueError, match=rf"^vertical_input_invalid:{field}$"):
        run_open_interest_and_funding_vertical(**_runtime_args(input_helpers, **{field: value}))


@pytest.mark.parametrize("field", ["include_snapshots", "include_confirmations", "is_demo", "include_debug_bundle"])
@pytest.mark.parametrize("value", [0, 1, None, "true"])
def test_runtime_boolean_flags(input_helpers, field, value):
    with pytest.raises(ValueError, match=rf"^vertical_input_invalid:{field}$"):
        run_open_interest_and_funding_vertical(**_runtime_args(input_helpers, **{field: value}))


@pytest.mark.parametrize(("data_mode", "is_demo", "reason"), [
    ("other", False, "data_mode"), ("live", True, "is_demo"), ("synthetic", False, "is_demo"),
])
def test_runtime_data_mode_demo_coherence(input_helpers, data_mode, is_demo, reason):
    with pytest.raises(ValueError, match=rf"^vertical_input_invalid:{reason}$"):
        run_open_interest_and_funding_vertical(**_runtime_args(
            input_helpers, data_mode=data_mode, is_demo=is_demo))


def test_runtime_calls_input_once_with_exact_arguments_and_preserves_callers(monkeypatch, input_contract):
    state, requests, seen = copy.deepcopy(input_contract), [{"x": 1}], []
    before_state, before_requests = copy.deepcopy(state), copy.deepcopy(requests)
    monkeypatch.setattr(vertical, "run_open_interest_and_funding_input",
                        lambda **kwargs: seen.append(kwargs) or {**copy.deepcopy(input_contract), "mode": "recovery"})
    monkeypatch.setattr(vertical, "build_open_interest_and_funding_screen",
                        lambda value, **kwargs: {"mode": value["mode"], **kwargs})
    marker = object()
    result = run_open_interest_and_funding_vertical(
        mode="recovery", fetcher=marker, reference_timestamp=1, execution_timestamp=2,
        input_state=state, recovery_requests=requests,
    )
    assert len(seen) == 1 and seen[0] == {
        "fetcher": marker, "reference_timestamp": 1, "requested_mode": "recovery",
        "recovery_requests": requests, "existing_state": state, "include_snapshots": True,
        "include_confirmations": True, "data_mode": "live", "is_demo": False,
        "execution_timestamp": 2,
    }
    assert state == before_state and requests == before_requests and result["mode"] == "recovery"


def test_static_scope_has_only_public_stages_no_clock_network_registry_or_writes():
    source = SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
               for alias in node.names}
    prohibited = ("processing.math", "Processor", "Classifier", "requests", "urllib", "socket",
                  "input_pipeline", "processing_pipeline", "classification_pipeline", "main_pipeline")
    assert not any(token in source for token in prohibited)
    assert not ({"time", "datetime", "uuid", "random", "os"} & imports)
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"open", "hash"} for node in ast.walk(tree))

