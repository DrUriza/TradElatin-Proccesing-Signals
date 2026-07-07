from __future__ import annotations

from pathlib import Path
from typing import Any

from processing_signals.processing.classification_input import ClassificationInput
from processing_signals.processing.classification_output import ClassificationOutput
from processing_signals.processing.extraction import ProcessingExtraction
from processing_signals.processing.math.math_engine import ProcessingMathEngine
from processing_signals.processing.normalization.processing_normalization import ProcessingNormalization
from processing_signals.processing.patterns.pattern_engine import PatternEngine
from processing_signals.processing.transforms.transform_engine import TransformEngine
from processing_signals.processing.union import ProcessingUnion


class ProcessingPipeline:
    """Orchestrates Processing without doing stage work directly."""

    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        max_rows: int | None = None,
        write_validation_report: bool = False,
        write_manifest: bool = False,
        input_timeframe_issues: list[dict[str, Any]] | None = None,
        extraction: ProcessingExtraction | None = None,
        classification_input: ClassificationInput | None = None,
        normalization: ProcessingNormalization | None = None,
        transform_engine: TransformEngine | None = None,
        math_engine: ProcessingMathEngine | None = None,
        pattern_engine: PatternEngine | None = None,
        classification_output: ClassificationOutput | None = None,
        union: ProcessingUnion | None = None,
    ):
        self.input_path = Path(input_path)
        self.output_path = Path(output_path)
        self.write_validation_report = write_validation_report
        self.write_manifest = write_manifest
        self.input_timeframe_issues = list(input_timeframe_issues or [])
        self.extraction = extraction or ProcessingExtraction(self.input_path)
        self.classification_input = classification_input or ClassificationInput()
        self.normalization = normalization or ProcessingNormalization()
        self.transform_engine = transform_engine or TransformEngine()
        self.math_engine = math_engine or ProcessingMathEngine()
        self.pattern_engine = pattern_engine or PatternEngine()
        self.classification_output = classification_output or ClassificationOutput()
        self.union = union or ProcessingUnion(self.output_path, max_rows=max_rows or 500)

    def run(self) -> dict[str, Any]:
        extracted = self.extraction.extract()
        classified_input = self.classification_input.classify(extracted)
        normalized = self.normalization.normalize(classified_input)
        transformed = self.transform_engine.transform_blocks(normalized)
        computed = self.math_engine.compute_blocks(transformed, self.pattern_engine)
        classified_output = self.classification_output.classify(computed)
        return self.union.union(
            classified_output,
            write_manifest=self.write_manifest,
            input_timeframe_issues=self.input_timeframe_issues,
        )


MainPipeline = ProcessingPipeline
