from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, TypedDict

from .target_types import HMIWindowMode, ValidationLevel


class ProcessingBlock(TypedDict, total=False):
    source_name: str
    data_type: str
    symbol: str | None
    timeframe: str | None
    records: int
    columns: list[str]
    timestamp_field: str | None
    data: list[dict[str, Any]]
    events: list[dict[str, Any]]
    bids: list[dict[str, Any]]
    asks: list[dict[str, Any]]


class FamilyProcessingPayload(TypedDict, total=False):
    pipeline: str
    version: str
    family_key: str
    output_shape: str
    records_processed: int
    symbols: list[str]
    timeframes: list[str]
    data_types: dict[str, int]
    blocks: list[ProcessingBlock]


@dataclass(frozen=True)
class ValidationIssue:
    level: ValidationLevel
    message: str
    source_name: str | None = None
    output_shape: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ChartSeriesDescriptor:
    source_name: str
    data_type: str | None
    symbol: str | None
    timeframe: str | None
    output_shape: str
    x_field: str
    y_fields: list[str]
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyChartPayload:
    family_key: str
    module_key: str
    hmi_window_mode: HMIWindowMode
    selected_output_shape: str | None
    status: str
    records_processed: int
    symbols: list[str]
    timeframes: list[str]
    series: list[ChartSeriesDescriptor]
    issues: list[ValidationIssue]

    def to_dict(self) -> dict[str, Any]:
        item = asdict(self)
        item["series"] = [series.to_dict() for series in self.series]
        item["issues"] = [issue.to_dict() for issue in self.issues]
        return item
