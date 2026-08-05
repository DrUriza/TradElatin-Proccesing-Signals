import ast
from pathlib import Path

import pytest

from liquidity_microstructure_vertical_helpers import arguments
from processing_signals.main.liquidity_microstructure import LiquidityMicrostructureVerticalError, run_liquidity_microstructure_vertical


def test_invalid_arguments_and_no_math_import():
    with pytest.raises(LiquidityMicrostructureVerticalError):
        run_liquidity_microstructure_vertical(**arguments(mode="bad"))
    with pytest.raises(LiquidityMicrostructureVerticalError):
        run_liquidity_microstructure_vertical(**arguments(fetcher=None))
    path = Path("src/processing_signals/main/liquidity_microstructure/liquidity_microstructure_vertical.py")
    modules = [node.module for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))) if isinstance(node, ast.ImportFrom)]
    assert "processing_signals.processing.math.microstructure" not in modules
