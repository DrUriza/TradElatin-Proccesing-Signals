import pytest

from processing_signals.classification.classification_pipeline import CLASSIFICATION_FAMILY_HANDLERS, run_classification_pipeline
from processing_signals.input.input_pipeline import INPUT_FAMILY_HANDLERS, run_input_pipeline
from processing_signals.main.main_pipeline import VERTICAL_FAMILY_HANDLERS
from processing_signals.processing.processing_pipeline import PROCESSING_FAMILY_HANDLERS, run_processing_pipeline


def test_all_canonical_handlers_are_registered_without_changing_defaults():
    for registry in (INPUT_FAMILY_HANDLERS, PROCESSING_FAMILY_HANDLERS, CLASSIFICATION_FAMILY_HANDLERS,
                     VERTICAL_FAMILY_HANDLERS):
        assert "prices_ohlcv" in registry and "long_short_liquidations" in registry


@pytest.mark.parametrize("runner,kwargs", [(run_input_pipeline, {}),
    (run_processing_pipeline, {"input_contracts": {}}),
    (run_classification_pipeline, {"processing_contracts": {}})])
def test_unknown_and_legacy_families_are_rejected(runner, kwargs):
    with pytest.raises(ValueError):
        runner(enabled_families=("liquidations",), **kwargs)
