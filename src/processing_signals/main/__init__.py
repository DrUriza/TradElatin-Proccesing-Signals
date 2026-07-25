from __future__ import annotations

__all__ = ["VERTICAL_FAMILY_HANDLERS", "run_main_pipeline"]


def __getattr__(name: str):
    if name in __all__:
        from .main_pipeline import VERTICAL_FAMILY_HANDLERS, run_main_pipeline

        return {"VERTICAL_FAMILY_HANDLERS": VERTICAL_FAMILY_HANDLERS, "run_main_pipeline": run_main_pipeline}[name]
    raise AttributeError(name)
