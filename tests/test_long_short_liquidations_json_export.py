import json
import os

import pytest

from processing_signals.main.screen_contract_export import export_long_short_liquidations_screen_json, write_long_short_liquidations_screen_json
from long_short_liquidations_integration_helpers import run_vertical


def test_export_writes_only_screen_for_path_and_string(tmp_path):
    output = run_vertical()
    for target in (tmp_path / "path.json", str(tmp_path / "string.json")):
        destination = export_long_short_liquidations_screen_json(vertical_output=output, output_path=target)
        parsed = json.loads(destination.read_text(encoding="utf-8"))
        assert parsed == output["screen"] and "screen" not in parsed and destination.read_bytes().endswith(b"\n")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_export_rejects_non_finite_before_replacing(tmp_path, value):
    output = run_vertical()
    output["screen"]["hostile"] = value
    target = tmp_path / "screen.json"
    target.write_text("previous\n", encoding="utf-8")
    with pytest.raises(ValueError):
        export_long_short_liquidations_screen_json(vertical_output=output, output_path=target)
    assert target.read_text(encoding="utf-8") == "previous\n" and not list(tmp_path.glob("*.tmp"))


def test_replace_failure_preserves_previous_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "screen.json"
    target.write_text("previous\n", encoding="utf-8")
    monkeypatch.setattr(os, "replace", lambda *_: (_ for _ in ()).throw(OSError("replace failed")))
    with pytest.raises(OSError):
        export_long_short_liquidations_screen_json(vertical_output=run_vertical(), output_path=target)
    assert target.read_text(encoding="utf-8") == "previous\n" and not list(tmp_path.glob("*.tmp"))


def test_fsync_failure_preserves_previous_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / "screen.json"
    target.write_text("previous\n", encoding="utf-8")
    monkeypatch.setattr(os, "fsync", lambda *_: (_ for _ in ()).throw(OSError("fsync failed")))
    with pytest.raises(OSError):
        export_long_short_liquidations_screen_json(vertical_output=run_vertical(), output_path=target)
    assert target.read_text(encoding="utf-8") == "previous\n" and not list(tmp_path.glob("*.tmp"))


def test_contract_identity_is_validated_before_write(tmp_path):
    screen = run_vertical()["screen"]
    for key in ("family", "screen_id", "contract_version", "quality"):
        invalid = dict(screen)
        invalid.pop(key)
        with pytest.raises(ValueError):
            write_long_short_liquidations_screen_json(screen_contract=invalid, output_path=tmp_path / f"{key}.json")
