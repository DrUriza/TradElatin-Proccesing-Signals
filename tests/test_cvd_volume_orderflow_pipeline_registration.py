from __future__ import annotations

from pathlib import Path
import runpy

from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS, run_main_pipeline

FAMILY = "cvd_volume_orderflow"
INPUT_TEST = Path(__file__).with_name("test_cvd_volume_orderflow_input_vertical.py")


def arguments():
    helpers = runpy.run_path(str(INPUT_TEST))
    return {"fetcher": helpers["fetcher"], "reference_timestamp": helpers["REFERENCE"],
        "clock": lambda: helpers["REFERENCE"], "target_display_records": 1, "warmup_records": 0,
        "display_point_limit": 1, "include_footprint": False, "include_cryptoquant_confirmation": False,
        "include_glassnode_confirmation": False}


def test_registered_handler_and_global_route():
    assert FAMILY in VERTICAL_FAMILY_HANDLERS
    output = run_main_pipeline(enabled_families=(FAMILY,), family_arguments={FAMILY: arguments()})[FAMILY]
    assert tuple(output) == ("screen",)
    assert output["screen"]["screen"]["id"] == FAMILY
    assert output["screen"]["stage"] == "screen_contract"


def test_screens_only_is_semantically_identical():
    normal = run_main_pipeline(enabled_families=(FAMILY,), family_arguments={FAMILY: arguments()})[FAMILY]["screen"]
    direct = run_main_pipeline(enabled_families=(FAMILY,), screens_only=True,
        family_arguments={FAMILY: arguments()})[FAMILY]
    assert direct == normal
