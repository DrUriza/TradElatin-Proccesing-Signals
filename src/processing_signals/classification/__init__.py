__all__ = ["ClassificationPipeline"]


def __getattr__(name: str):
	if name == "ClassificationPipeline":
		from .classification_pipeline import ClassificationPipeline

		return ClassificationPipeline
	raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
