from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import runpy

import pytest

import processing_signals.main.screen_contract_export as exporter
from processing_signals.main.open_interest_and_funding import build_open_interest_and_funding_screen
from processing_signals.main.screen_contract_export import (
    DEFAULT_OPEN_INTEREST_AND_FUNDING_OUTPUT_PATH,
    write_open_interest_and_funding_screen_json,
)


PROCESSING_TEST = Path(__file__).with_name("test_open_interest_and_funding_processing_vertical.py")


@pytest.fixture(scope="session")
def screen() -> dict:
    source = runpy.run_path(str(PROCESSING_TEST))["_input"]()
    return build_open_interest_and_funding_screen(source)


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)


def test_default_constant_and_function_present():
    assert DEFAULT_OPEN_INTEREST_AND_FUNDING_OUTPUT_PATH == Path(
        "runtime/contracts/open_interest_and_funding_screen.json")
    assert callable(write_open_interest_and_funding_screen_json)


@pytest.mark.parametrize("value", [None, [], "x", 1, True])
def test_screen_mapping_required(value):
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract=value)


@pytest.mark.parametrize(("mutation", "value"), [
    ("family", "wrong"), ("stage", "wrong"), ("version", "9"), ("quality", []),
])
def test_screen_identity_and_quality_mapping(screen, mutation, value):
    candidate = copy.deepcopy(screen)
    candidate[mutation] = value
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract=candidate)


@pytest.mark.parametrize("status", [None, "available", "unavailable", 1])
def test_quality_status_enum(screen, status):
    candidate = copy.deepcopy(screen)
    candidate["quality"]["status"] = status
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract=candidate)


def test_root_exact_and_debug_rejected(screen):
    candidate = copy.deepcopy(screen)
    candidate["extra"] = 1
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract=candidate)
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract={"screen": screen})


@pytest.mark.parametrize("value", [None, 0, 1, "false", []])
def test_allow_invalid_exact_bool(screen, value):
    with pytest.raises(ValueError, match="^vertical_export_invalid:allow_invalid$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen, allow_invalid=value)


def test_invalid_policy_and_ok_partial_export(screen):
    invalid = copy.deepcopy(screen)
    invalid["quality"]["status"] = "invalid"
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen_invalid$"):
        write_open_interest_and_funding_screen_json(screen_contract=invalid)
    allowed = write_open_interest_and_funding_screen_json(
        screen_contract=invalid, output_path="runtime/contracts/invalid.json", allow_invalid=True)
    assert allowed == Path("runtime/contracts/invalid.json") and allowed.exists()
    for status in ("ok", "partial"):
        candidate = copy.deepcopy(screen)
        candidate["quality"]["status"] = status
        assert write_open_interest_and_funding_screen_json(
            screen_contract=candidate, output_path=f"runtime/contracts/{status}.json").exists()


def test_default_path_utf8_lf_compact_json_and_no_mutation(screen):
    candidate = copy.deepcopy(screen)
    before = copy.deepcopy(candidate)
    result = write_open_interest_and_funding_screen_json(screen_contract=candidate)
    assert result == DEFAULT_OPEN_INTEREST_AND_FUNDING_OUTPUT_PATH
    raw = result.read_bytes()
    assert raw.endswith(b"\n") and b": " not in raw
    assert json.loads(raw.decode("utf-8")) == screen and candidate == before


@pytest.mark.parametrize("as_string", [False, True])
def test_relative_and_absolute_internal_paths(screen, as_string):
    destination = Path.cwd() / "runtime" / "contracts" / "nested" / "screen.json"
    value = str(destination) if as_string else destination
    result = write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=value)
    assert result == Path(value) and destination.exists()


@pytest.mark.parametrize("path", ["", "runtime/contracts/screen.txt", "../screen.json",
                                   "runtime/../screen.json"])
def test_unsafe_paths_rejected_before_writing(screen, path):
    with pytest.raises(ValueError, match="^vertical_export_invalid:path$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=path)


def test_external_absolute_path_and_directory_rejected(screen, tmp_path):
    external = tmp_path.parent / "external.json"
    with pytest.raises(ValueError, match="^vertical_export_invalid:path$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=external)
    directory = Path("runtime/contracts/directory.json")
    directory.mkdir(parents=True)
    with pytest.raises(ValueError, match="^vertical_export_invalid:path$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=directory)


def test_symlink_escape_rejected_when_supported(screen, tmp_path):
    root = Path("runtime/contracts")
    root.mkdir(parents=True)
    link = root / "escape"
    try:
        link.symlink_to(tmp_path.parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(ValueError, match="^vertical_export_invalid:path$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen,
                                                    output_path=link / "screen.json")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), b"x", {1}, (1,)])
def test_non_json_values_fail_before_touching_destination(screen, value):
    destination = Path("runtime/contracts/screen.json")
    destination.parent.mkdir(parents=True)
    destination.write_text("previous\n", encoding="utf-8")
    candidate = copy.deepcopy(screen)
    candidate["hostile"] = value
    with pytest.raises(ValueError, match="^vertical_export_invalid:screen$"):
        write_open_interest_and_funding_screen_json(screen_contract=candidate, output_path=destination)
    assert destination.read_text(encoding="utf-8") == "previous\n"


def test_non_string_nested_key_is_serialization_error(screen):
    candidate = copy.deepcopy(screen)
    candidate["quality"][1] = "bad"
    with pytest.raises(ValueError, match="^vertical_export_invalid:serialization$"):
        write_open_interest_and_funding_screen_json(screen_contract=candidate)


def test_atomic_replace_and_deterministic_bytes(screen):
    destination = Path("runtime/contracts/screen.json")
    destination.parent.mkdir(parents=True)
    destination.write_text("previous\n", encoding="utf-8")
    write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=destination)
    first = destination.read_bytes()
    write_open_interest_and_funding_screen_json(screen_contract=copy.deepcopy(screen), output_path=destination)
    assert destination.read_bytes() == first and json.loads(first) == screen
    assert not list(destination.parent.glob("*.tmp"))


@pytest.mark.parametrize("failure", ["fsync", "replace"])
def test_atomic_failure_preserves_previous_and_cleans_temp(screen, monkeypatch, failure):
    destination = Path("runtime/contracts/screen.json")
    destination.parent.mkdir(parents=True)
    destination.write_text("previous\n", encoding="utf-8")
    if failure == "fsync":
        monkeypatch.setattr(exporter.os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    else:
        monkeypatch.setattr(exporter.os, "replace", lambda *_: (_ for _ in ()).throw(OSError("fail")))
    with pytest.raises(ValueError, match="^vertical_export_invalid:write$"):
        write_open_interest_and_funding_screen_json(screen_contract=screen, output_path=destination)
    assert destination.read_text(encoding="utf-8") == "previous\n"
    assert not list(destination.parent.glob("*.tmp"))


def test_exporter_does_not_call_pipeline_layers(screen, monkeypatch):
    for name in ("run_open_interest_and_funding_input", "process_open_interest_and_funding",
                 "classify_open_interest_and_funding", "build_open_interest_and_funding_contract"):
        monkeypatch.setattr(exporter, name, lambda: pytest.fail(name), raising=False)
    write_open_interest_and_funding_screen_json(screen_contract=screen)


def test_existing_exporter_apis_remain_present():
    for name in ("write_long_short_liquidations_screen_json", "export_long_short_liquidations_screen_json",
                 "write_on_chain_miners_screen_json", "export_on_chain_miners_screen_json",
                 "write_etf_exchange_flows_screen_json", "export_etf_exchange_flows_screen_json"):
        assert callable(getattr(exporter, name))

