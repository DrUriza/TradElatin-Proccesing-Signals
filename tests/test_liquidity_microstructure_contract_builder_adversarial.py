import ast
# ruff: noqa: E702
import json
from copy import deepcopy
from pathlib import Path

import pytest

from liquidity_microstructure_contract_builder_helpers import bundle, runtime
from processing_signals.classification.liquidity_microstructure.liquidity_microstructure_contract_builder import build_liquidity_microstructure_screen_contract


@pytest.mark.parametrize(("market", "timeframe", "limit"), [("other", "1m", 1), ("spot", "2m", 1), ("spot", "1m", 0), ("spot", "1m", True)])
def test_invalid_arguments(market, timeframe, limit):
    with pytest.raises(ValueError):
        build_liquidity_microstructure_screen_contract(bundle(), runtime_context=runtime(), selected_market=market,
                                                       selected_timeframe=timeframe, display_point_limit=limit)


def test_deterministic_immutable_strict_json_and_no_math_import():
    source, operation = bundle(), runtime(); before_source, before_operation = deepcopy(source), deepcopy(operation)
    one = build_liquidity_microstructure_screen_contract(source, runtime_context=operation)
    two = build_liquidity_microstructure_screen_contract(source, runtime_context=operation)
    assert json.dumps(one, ensure_ascii=False, allow_nan=False, separators=(",", ":")) == json.dumps(two, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    assert source == before_source and operation == before_operation
    module = ast.parse(Path("src/processing_signals/classification/liquidity_microstructure/liquidity_microstructure_contract_builder.py").read_text(encoding="utf-8"))
    assert "processing_signals.processing.math.microstructure" not in [node.module for node in ast.walk(module) if isinstance(node, ast.ImportFrom)]


def test_runtime_requires_timezone_and_consistent_demo_mode():
    with pytest.raises(ValueError):
        build_liquidity_microstructure_screen_contract(bundle(), runtime_context=runtime(generated_at="2025-01-01T00:00:00"))
    with pytest.raises(ValueError):
        build_liquidity_microstructure_screen_contract(bundle(), runtime_context=runtime(is_demo=False))
