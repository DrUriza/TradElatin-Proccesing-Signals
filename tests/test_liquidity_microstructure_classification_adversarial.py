import ast
from pathlib import Path

import pytest

from liquidity_microstructure_classification_helpers import processing_contract
from processing_signals.classification.liquidity_microstructure import classify_liquidity_microstructure


@pytest.mark.parametrize(("field", "value"), [("family", "wrong"), ("stage", "input"), ("mode", "wrong")])
def test_invalid_root_contract(field, value):
    source = processing_contract()
    source[field] = value
    with pytest.raises(ValueError):
        classify_liquidity_microstructure(source)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.0])
def test_invalid_json_numbers(value):
    source = processing_contract()
    source["reference_timestamp"] = value
    with pytest.raises(ValueError):
        classify_liquidity_microstructure(source)


def test_no_microstructure_math_import():
    path = Path("src/processing_signals/classification/liquidity_microstructure/liquidity_microstructure_classifier.py")
    modules = [node.module for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)]
    assert "processing_signals.processing.math.microstructure" not in modules
