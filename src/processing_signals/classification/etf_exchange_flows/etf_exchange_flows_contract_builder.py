"""Screen Contract Builder v0.1 for frozen ETF exchange-flow contracts."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import json
import math
from typing import Any

FAMILY = "etf_exchange_flows"
UPSTREAM_VERSION = "0.1"
CONTRACT_VERSION = "0.1"
SCHEMA_ID = "trad_elatin.etf_exchange_flows.screen.v1"
SCHEMA_VERSION = "1.0.0"
RANGE_SECONDS = {"1d": 86_400, "7d": 604_800, "30d": 2_592_000, "90d": 7_776_000}
ALLOWED_RANGES = tuple(RANGE_SECONDS)
VALID_STATUSES = {"available", "partial", "unavailable", "invalid"}

REQUIRED_VIEWS = (
    "kpis.etf_net_flow", "kpis.total_aum", "kpis.exchange_inflow",
    "kpis.exchange_outflow", "kpis.exchange_balance", "kpis.exchange_flow_pressure",
    "charts.etf_flow_daily", "charts.etf_cumulative_net_flow",
    "charts.exchange_net_flow", "charts.exchange_balance", "tables.etf_funds",
    "classification_states.etf_flow_direction", "classification_states.etf_flow_persistence",
    "classification_states.exchange_pressure_regime",
    "classification_states.composite_capital_flow_regime", "classification_states.data_confidence",
)
OPTIONAL_VIEWS = (
    "kpis.gbtc_premium", "classification_states.gbtc_premium_regime",
    "classification_states.exchange_netflow_regime",
    "classification_states.aum_reconciliation_state", "provider_reconciliation",
    "charts.exchange_balance.overlays.glassnode_balance_secondary", "tables.etf_funds.issuer_flow",
)


def _timestamp(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return value


def _identity(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _at(root: Mapping[str, Any], path: str, default: Any = None) -> Any:
    value: Any = root
    for name in path.split("."):
        if not isinstance(value, Mapping) or name not in value:
            return default
        value = value[name]
    return value


def _json_copy(value: Any, path: str = "root") -> Any:
    if isinstance(value, Mapping):
        copied: dict[str, Any] = {}
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError(f"non_json_contract_value:{path}:key")
            copied[key] = _json_copy(child, f"{path}.{key}")
        return copied
    if isinstance(value, list):
        return [_json_copy(child, f"{path}[{index}]") for index, child in enumerate(value)]
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    raise ValueError(f"non_json_contract_value:{path}:{type(value).__name__}")


def _validate_upstream(contract: Any, *, stage: str) -> list[str]:
    if not isinstance(contract, Mapping):
        return [f"invalid_{stage}_contract"]
    errors = []
    for field, expected in (("family", FAMILY), ("stage", stage), ("version", UPSTREAM_VERSION)):
        if contract.get(field) != expected:
            errors.append(f"invalid_{stage}_{field}")
    required = ("features", "series", "snapshots", "series_metadata", "quality", "provenance") if stage == "processing" else (
        "classifications", "quality", "provenance")
    for field in required:
        if not isinstance(contract.get(field), Mapping):
            errors.append(f"invalid_{stage}_{field}")
    if _timestamp(contract.get("data_as_of")) is None:
        errors.append(f"invalid_{stage}_data_as_of")
    return errors


def _unavailable_financial(*, source_path: str, unit: str, status: str = "unavailable",
                           reason: str = "source_unavailable") -> dict[str, Any]:
    return {"status": status, "reason": reason, "value": None, "unit": unit, "data_as_of": None,
            "provider": None, "endpoint_id": None, "source_path": source_path, "warnings": []}


def _financial(feature: Any, *, source_path: str, unit: str, processing_anchor: int) -> dict[str, Any]:
    if not isinstance(feature, Mapping):
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_feature_invalid")
    status = feature.get("status")
    if status not in VALID_STATUSES:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_status_invalid")
    source_unit = feature.get("unit")
    if source_unit != unit:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_unit_incompatible")
    warnings = feature.get("warnings", [])
    if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_warnings_invalid")
    if status in {"unavailable", "invalid"}:
        return {**_unavailable_financial(source_path=source_path, unit=unit, status=status,
                                         reason=feature.get("reason") or f"source_{status}"),
                "provider": deepcopy(feature.get("provider")) if isinstance(feature.get("provider"), str) else None,
                "endpoint_id": deepcopy(feature.get("endpoint_id")) if isinstance(feature.get("endpoint_id"), str) else None,
                "warnings": list(warnings)}
    value = _number(feature.get("value"))
    anchor = _timestamp(feature.get("data_as_of"))
    if value is None:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_numeric_invalid")
    if anchor is None or anchor > processing_anchor:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="upstream_timestamp_inconsistent")
    provider = feature.get("provider")
    endpoint_id = feature.get("endpoint_id")
    if provider is not None and _identity(provider) is None:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_identity_invalid")
    if endpoint_id is not None and _identity(endpoint_id) is None:
        return _unavailable_financial(source_path=source_path, unit=unit, status="invalid",
                                      reason="source_identity_invalid")
    return {"status": status, "reason": deepcopy(feature.get("reason")), "value": value, "unit": unit,
            "data_as_of": anchor, "provider": deepcopy(provider), "endpoint_id": deepcopy(endpoint_id),
            "source_path": source_path, "warnings": list(warnings)}


def _chart(*, chart_id: str, source: Any, value_field: str, unit: str, source_path: str,
           anchor: int, range_seconds: int, identities: Sequence[str] = ()) -> dict[str, Any]:
    base = {"chart_id": chart_id, "status": "unavailable", "reason": "source_series_empty", "unit": unit,
            "source_path": source_path, "points": [], "data_as_of": None, "warnings": []}
    if not isinstance(source, list):
        return {**base, "status": "invalid", "reason": "source_series_invalid"}
    lower = anchor - range_seconds
    points, invalid = [], 0
    for record in source:
        if not isinstance(record, Mapping):
            invalid += 1
            continue
        timestamp = _timestamp(record.get("timestamp"))
        value = _number(record.get(value_field))
        if timestamp is None or timestamp > anchor:
            invalid += 1
            continue
        if not lower < timestamp <= anchor:
            continue
        identity_values = {field: _identity(record.get(field)) for field in identities}
        if any(value is None for value in identity_values.values()):
            invalid += 1
            continue
        provider = _identity(record.get("provider"))
        endpoint_id = _identity(record.get("endpoint_id"))
        if value is None or provider is None or endpoint_id is None:
            invalid += 1
            continue
        points.append({"timestamp": timestamp, "value": value, **identity_values,
                       "provider": provider, "endpoint_id": endpoint_id})
    points.sort(key=lambda item: (item["timestamp"], *(item.get(field, "") for field in identities),
                                  item["provider"], item["endpoint_id"]))
    if points:
        status = "partial" if invalid else "available"
        reason = "source_points_invalid" if invalid else None
        return {**base, "status": status, "reason": reason, "points": points,
                "data_as_of": points[-1]["timestamp"], "warnings": [reason] if reason else []}
    if invalid:
        return {**base, "status": "invalid", "reason": "source_points_invalid"}
    return base


def _classification(wrapper: Any, *, source_path: str, processing_anchor: int) -> dict[str, Any]:
    if not isinstance(wrapper, Mapping):
        return {"state": None, "status": "invalid", "reason": "source_classification_invalid",
                "data_as_of": None, "evidence": {}, "source_features": [], "parameters": {}, "warnings": []}
    status = wrapper.get("status")
    if status not in VALID_STATUSES:
        status = "invalid"
    result = {name: _json_copy(wrapper.get(name), f"{source_path}.{name}") for name in
              ("state", "reason", "evidence", "source_features", "parameters", "warnings")}
    anchor = _timestamp(wrapper.get("data_as_of"))
    if status in {"available", "partial"} and (anchor is None or anchor > processing_anchor):
        return {"state": None, "status": "invalid", "reason": "upstream_timestamp_inconsistent",
                "data_as_of": None, "evidence": {}, "source_features": [source_path], "parameters": {}, "warnings": []}
    if status in {"unavailable", "invalid"}:
        result["state"] = None
        anchor = None
    return {"state": result["state"], "status": status, "reason": result["reason"],
            "data_as_of": anchor, "evidence": result["evidence"], "source_features": result["source_features"],
            "parameters": result["parameters"], "warnings": result["warnings"]}


def _fund_table(source: Any, *, selected_range: str, processing_anchor: int) -> dict[str, Any]:
    base = {"table_id": "etf_funds", "status": "unavailable", "reason": "source_records_empty",
            "selected_range": selected_range, "rows": [], "data_as_of": None, "warnings": []}
    if not isinstance(source, list):
        return {**base, "status": "invalid", "reason": "source_records_invalid"}
    rows, invalid = [], 0
    for item in source:
        if not isinstance(item, Mapping):
            invalid += 1
            continue
        ticker, fund_name = _identity(item.get("ticker")), _identity(item.get("fund_name"))
        provider, endpoint_id = _identity(item.get("provider")), _identity(item.get("endpoint_id"))
        periods = item.get("periods")
        period = periods.get(selected_range) if isinstance(periods, Mapping) else None
        if None in (ticker, fund_name, provider, endpoint_id) or not isinstance(period, Mapping):
            invalid += 1
            continue
        flow = _financial(period.get("period_flow_usd"), source_path=f"snapshots.funds.{ticker}.periods.{selected_range}.period_flow_usd",
                          unit="USD", processing_anchor=processing_anchor)
        share = _financial(period.get("period_signed_flow_share"), source_path=f"snapshots.funds.{ticker}.periods.{selected_range}.period_signed_flow_share",
                           unit="ratio", processing_anchor=processing_anchor)
        aum = _financial(item.get("aum_usd"), source_path=f"snapshots.funds.{ticker}.aum_usd",
                         unit="USD", processing_anchor=processing_anchor)
        aum_share = _financial(item.get("aum_share"), source_path=f"snapshots.funds.{ticker}.aum_share",
                               unit="ratio", processing_anchor=processing_anchor)
        issuer_source = item.get("issuer_flow")
        issuer = (_financial(issuer_source, source_path=f"snapshots.funds.{ticker}.issuer_flow", unit="USD",
                             processing_anchor=processing_anchor) if isinstance(issuer_source, Mapping) else
                  _unavailable_financial(source_path=f"snapshots.funds.{ticker}.issuer_flow", unit="USD",
                                         reason="issuer_identity_unavailable"))
        row_statuses = (flow["status"], aum["status"])
        row_status = "invalid" if "invalid" in row_statuses else "partial" if any(value != "available" for value in row_statuses) else "available"
        anchors = [value["data_as_of"] for value in (flow, aum) if value["status"] in {"available", "partial"}]
        rows.append({"ticker": ticker, "fund_name": fund_name, "provider": provider, "endpoint_id": endpoint_id,
                     "status": row_status, "reason": next((value["reason"] for value in (flow, aum) if value["reason"]), None),
                     "flow_usd": flow, "signed_flow_share": share, "aum_usd": aum, "aum_share": aum_share,
                     "issuer_flow": issuer, "data_as_of": min(anchors) if anchors else None, "warnings": []})
    rows.sort(key=lambda item: (item["ticker"], item["provider"], item["endpoint_id"]))
    if not rows:
        return {**base, "status": "invalid" if invalid else "unavailable",
                "reason": "source_records_invalid" if invalid else "source_records_empty"}
    table_status = "partial" if invalid or any(row["status"] != "available" for row in rows) else "available"
    anchors = [row["data_as_of"] for row in rows if row["data_as_of"] is not None]
    return {**base, "status": table_status, "reason": "source_records_invalid" if invalid else None,
            "rows": rows, "data_as_of": min(anchors) if anchors else None,
            "warnings": ["source_records_invalid"] if invalid else []}


def _view_statuses(root: Mapping[str, Any], selected_range: str) -> dict[str, str]:
    paths = {
        "kpis.etf_net_flow": "kpis.etf_net_flow", "kpis.total_aum": "kpis.total_aum",
        "kpis.exchange_inflow": "kpis.exchange_inflow", "kpis.exchange_outflow": "kpis.exchange_outflow",
        "kpis.exchange_balance": "kpis.exchange_balance", "kpis.exchange_flow_pressure": "kpis.exchange_flow_pressure",
        "charts.etf_flow_daily": "charts.etf_flow_daily", "charts.etf_cumulative_net_flow": "charts.etf_cumulative_net_flow",
        "charts.exchange_net_flow": "charts.exchange_net_flow", "charts.exchange_balance": "charts.exchange_balance",
        "tables.etf_funds": "tables.etf_funds",
        "classification_states.etf_flow_direction": f"classification_states.etf_flow_direction.{selected_range}",
        "classification_states.etf_flow_persistence": "classification_states.etf_flow_persistence",
        "classification_states.exchange_pressure_regime": "classification_states.exchange_pressure_regime",
        "classification_states.composite_capital_flow_regime": "classification_states.composite_capital_flow_regime",
        "classification_states.data_confidence": "classification_states.data_confidence",
    }
    return {name: str((_at(root, path, {}) or {}).get("status", "invalid")) for name, path in paths.items()}


def _fallback(errors: Sequence[str], *, selected_range: str, mode: Any = None,
              data_mode: Any = None, is_demo: Any = None) -> dict[str, Any]:
    output = {"schema": {"id": SCHEMA_ID, "version": SCHEMA_VERSION},
        "screen": {"id": FAMILY, "route": "/etf-exchange-flows", "title": "ETF & Exchange Flows", "family": FAMILY},
        "stage": "screen_contract", "version": CONTRACT_VERSION, "mode": deepcopy(mode), "data_mode": deepcopy(data_mode),
        "is_demo": deepcopy(is_demo), "context": {"generated_at": None, "processing_data_as_of": None,
            "classification_data_as_of": None, "data_as_of": None, "selected_range": selected_range,
            "calculation_history": "processing_precomputed_only"},
        "range_selector": {"selected": selected_range, "default": "30d",
            "options": [{"id": key, "seconds": value} for key, value in RANGE_SECONDS.items()]},
        "kpis": {}, "charts": {}, "tables": {}, "classification_states": {}, "provider_reconciliation": {},
        "operational_status": {"quality_status": "invalid", "connection_status": "not_reported",
            "cache_status": "not_reported", "generated_at": None, "data_as_of": None},
        "provenance": {"source_contracts": {}, "field_sources": {}, "providers": {}, "parameters": {}, "warnings": []},
        "quality": {"status": "invalid", "required": list(REQUIRED_VIEWS), "optional": list(OPTIONAL_VIEWS),
            "available": [], "partial": [], "unavailable": [], "invalid": list(REQUIRED_VIEWS),
            "data_as_of": None, "processing_status": "invalid", "classification_status": "invalid",
            "warnings": [], "errors": sorted(set(errors))}}
    json.dumps(output, ensure_ascii=False, allow_nan=False)
    return output


def build_etf_exchange_flows_contract(*, processing_contract: Mapping[str, Any],
                                      classification_contract: Mapping[str, Any], selected_range: str = "30d",
                                      generated_at: Any = None) -> dict[str, Any]:
    """Build a JSON-safe screen contract without mutating or recalculating upstream data."""
    if selected_range not in RANGE_SECONDS:
        raise ValueError("invalid_selected_range")
    processing_before = deepcopy(processing_contract)
    classification_before = deepcopy(classification_contract)
    errors = [*_validate_upstream(processing_contract, stage="processing"),
              *_validate_upstream(classification_contract, stage="classification")]
    mode = processing_contract.get("mode") if isinstance(processing_contract, Mapping) else None
    data_mode = processing_contract.get("data_mode") if isinstance(processing_contract, Mapping) else None
    is_demo = processing_contract.get("is_demo") if isinstance(processing_contract, Mapping) else None
    if errors:
        return _fallback(errors, selected_range=selected_range, mode=mode, data_mode=data_mode, is_demo=is_demo)
    processing = processing_contract
    classification = classification_contract
    processing_anchor = _timestamp(processing["data_as_of"])
    classification_anchor = _timestamp(classification["data_as_of"])
    assert processing_anchor is not None and classification_anchor is not None
    if classification_anchor > processing_anchor:
        return _fallback(["upstream_timestamp_inconsistent"], selected_range=selected_range,
                         mode=mode, data_mode=data_mode, is_demo=is_demo)
    seconds = RANGE_SECONDS[selected_range]
    features = processing["features"]
    series = processing["series"]
    kpi_sources = {
        "etf_net_flow": (f"features.etf.period_flow_usd.{selected_range}", "USD"),
        "total_aum": ("features.etf.reported_total_aum_usd", "USD"),
        "exchange_inflow": ("features.exchange_flows.inflow_24h", "BTC"),
        "exchange_outflow": ("features.exchange_flows.outflow_24h", "BTC"),
        "exchange_balance": ("features.exchange_balances.cryptoquant_reserve", "BTC"),
        "gbtc_premium": ("features.premium_discount.gbtc_latest", "percent"),
        "exchange_flow_pressure": ("features.pressure.flow_24h", "ratio"),
    }
    kpis = {name: _financial(_at(processing, path), source_path=path, unit=unit,
                             processing_anchor=processing_anchor) for name, (path, unit) in kpi_sources.items()}
    interval = "hour" if selected_range in {"1d", "7d"} else "day"
    charts = {
        "etf_flow_daily": _chart(chart_id="etf_flow_daily", source=series.get("etf_flow_daily"), value_field="flow_usd",
            unit="USD", source_path="series.etf_flow_daily", anchor=processing_anchor, range_seconds=seconds),
        "etf_cumulative_net_flow": _chart(chart_id="etf_cumulative_net_flow", source=series.get("etf_cumulative_flow"),
            value_field="cumulative_flow_usd", unit="USD", source_path="series.etf_cumulative_flow",
            anchor=processing_anchor, range_seconds=seconds),
        "exchange_net_flow": _chart(chart_id="exchange_net_flow", source=_at(processing, f"series.exchange_netflow.{interval}"),
            value_field="netflow_total", unit="BTC", source_path=f"series.exchange_netflow.{interval}",
            anchor=processing_anchor, range_seconds=seconds),
        "exchange_balance": _chart(chart_id="exchange_balance", source=series.get("exchange_balance"), value_field="balance_btc",
            unit="BTC", source_path="series.exchange_balance", anchor=processing_anchor, range_seconds=seconds,
            identities=("exchange_name", "symbol")),
    }
    charts["exchange_balance"]["overlays"] = {"glassnode_balance_secondary": {
        "status": "unavailable", "reason": "overlay_semantics_not_confirmed", "series": []}}
    tables = {"etf_funds": _fund_table(processing["snapshots"].get("funds"), selected_range=selected_range,
                                        processing_anchor=processing_anchor)}
    source_classifications = classification["classifications"]
    direction_source = source_classifications.get("etf_flow_direction")
    directions = {name: _classification(direction_source.get(name) if isinstance(direction_source, Mapping) else None,
        source_path=f"classifications.etf_flow_direction.{name}", processing_anchor=processing_anchor) for name in ALLOWED_RANGES}
    state_names = ("etf_flow_persistence", "gbtc_premium_regime", "exchange_pressure_regime",
                   "exchange_netflow_regime", "aum_reconciliation_state", "composite_capital_flow_regime", "data_confidence")
    classification_states = {"etf_flow_direction": directions, **{
        name: _classification(source_classifications.get(name), source_path=f"classifications.{name}",
                              processing_anchor=processing_anchor) for name in state_names}}
    reconciliation = _json_copy(_at(features, "provider_reconciliation", {}), "provider_reconciliation")
    root: dict[str, Any] = {"schema": {"id": SCHEMA_ID, "version": SCHEMA_VERSION},
        "screen": {"id": FAMILY, "route": "/etf-exchange-flows", "title": "ETF & Exchange Flows", "family": FAMILY},
        "stage": "screen_contract", "version": CONTRACT_VERSION, "mode": deepcopy(mode), "data_mode": deepcopy(data_mode),
        "is_demo": deepcopy(is_demo), "context": {"generated_at": deepcopy(generated_at if generated_at is not None else processing.get("generated_at")),
            "processing_data_as_of": processing_anchor, "classification_data_as_of": classification_anchor,
            "data_as_of": None, "selected_range": selected_range, "calculation_history": "processing_precomputed_only"},
        "range_selector": {"selected": selected_range, "default": "30d",
            "options": [{"id": key, "seconds": value} for key, value in RANGE_SECONDS.items()]},
        "kpis": kpis, "charts": charts, "tables": tables, "classification_states": classification_states,
        "provider_reconciliation": reconciliation,
        "operational_status": {"quality_status": None, "connection_status": "not_reported", "cache_status": "not_reported",
            "generated_at": deepcopy(generated_at if generated_at is not None else processing.get("generated_at")), "data_as_of": None},
        "provenance": {"source_contracts": {
            "processing": {"family": FAMILY, "stage": "processing", "version": UPSTREAM_VERSION,
                "data_as_of": processing_anchor, "quality_status": processing["quality"].get("status")},
            "classification": {"family": FAMILY, "stage": "classification", "version": UPSTREAM_VERSION,
                "data_as_of": classification_anchor, "quality_status": classification["quality"].get("status")}},
            "field_sources": {name: {"source_path": path, "provider": kpis[name]["provider"],
                "endpoint_id": kpis[name]["endpoint_id"]} for name, (path, _) in kpi_sources.items()},
            "providers": {"primary": {"etf": ["coinglass"], "exchange_flow": ["cryptoquant"],
                "exchange_balance_kpi": ["cryptoquant"], "exchange_balance_chart": ["coinglass"]},
                "secondary": {"exchange_balance": ["glassnode"]}},
            "parameters": {"selected_range": selected_range, "allowed_ranges": list(ALLOWED_RANGES),
                "range_seconds": seconds, "exchange_netflow_source_interval": interval,
                "exchange_flow_kpi_window_seconds": 86_400, "cumulative_series_rebased": False}, "warnings": []},
        "quality": {}}
    statuses = _view_statuses(root, selected_range)
    available = sorted(name for name, status in statuses.items() if status == "available")
    partial = sorted(name for name, status in statuses.items() if status == "partial")
    unavailable = sorted(name for name, status in statuses.items() if status == "unavailable")
    invalid = sorted(name for name, status in statuses.items() if status == "invalid")
    usable = [name for name, status in statuses.items() if status in {"available", "partial"}]
    quality_status = "invalid" if invalid or not usable else "ok" if len(available) == len(REQUIRED_VIEWS) else "partial"
    anchors = [processing_anchor, classification_anchor]
    for name in usable:
        path = name if not name.startswith("classification_states.etf_flow_direction") else f"classification_states.etf_flow_direction.{selected_range}"
        value = _at(root, path, {})
        timestamp = _timestamp(value.get("data_as_of")) if isinstance(value, Mapping) else None
        if timestamp is not None:
            anchors.append(timestamp)
    data_as_of = min(anchors) if quality_status != "invalid" else None
    root["quality"] = {"status": quality_status, "required": list(REQUIRED_VIEWS), "optional": list(OPTIONAL_VIEWS),
        "available": available, "partial": partial, "unavailable": unavailable, "invalid": invalid,
        "data_as_of": data_as_of, "processing_status": processing["quality"].get("status"),
        "classification_status": classification["quality"].get("status"), "warnings": [], "errors": []}
    root["context"]["data_as_of"] = data_as_of
    root["operational_status"].update(quality_status=quality_status, data_as_of=data_as_of)
    output = _json_copy(root, "screen_contract")
    json.dumps(output, ensure_ascii=False, allow_nan=False)
    if processing_contract != processing_before or classification_contract != classification_before:
        raise RuntimeError("Contract Builder mutated an upstream contract")
    return output


def run_etf_exchange_flows_contract_builder(*, processing_contract: Mapping[str, Any],
                                            classification_contract: Mapping[str, Any], selected_range: str = "30d",
                                            generated_at: Any = None) -> dict[str, Any]:
    return build_etf_exchange_flows_contract(processing_contract=processing_contract,
        classification_contract=classification_contract, selected_range=selected_range, generated_at=generated_at)


class EtfExchangeFlowsContractBuilder:
    def build(self, *, processing_contract: Mapping[str, Any], classification_contract: Mapping[str, Any],
              selected_range: str = "30d", generated_at: Any = None) -> dict[str, Any]:
        return build_etf_exchange_flows_contract(processing_contract=processing_contract,
            classification_contract=classification_contract, selected_range=selected_range, generated_at=generated_at)
