from liquidity_microstructure_processing_helpers import liquidity_input
from processing_signals.processing.liquidity_microstructure.liquidity_microstructure_processor import process_liquidity_microstructure


def processing_contract(*, mode="bootstrap"):
    return process_liquidity_microstructure(liquidity_input(mode=mode))
