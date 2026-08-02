from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from typing import Any


DEFAULT_OPEN_INTEREST_AND_FUNDING_OUTPUT_PATH = Path(
    "runtime/contracts/open_interest_and_funding_screen.json"
)
OPEN_INTEREST_AND_FUNDING_SCREEN_ROOT = (
    "schema", "screen", "stage", "mode", "context", "timeframe_selector", "operational_status",
    "kpis", "charts", "tables", "widgets", "drilldowns", "events", "availability", "quality",
)


def _validate_open_interest_and_funding_json(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return
    if type(value) is float:
        if not __import__("math").isfinite(value):
            raise ValueError("vertical_export_invalid:serialization")
        return
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("vertical_export_invalid:serialization")
        for item in value.values():
            _validate_open_interest_and_funding_json(item)
        return
    if isinstance(value, list):
        for item in value:
            _validate_open_interest_and_funding_json(item)
        return
    raise ValueError("vertical_export_invalid:serialization")


def _open_interest_and_funding_destination(output_path: str | Path) -> tuple[Path, Path]:
    if not isinstance(output_path, (str, Path)) or isinstance(output_path, str) and not output_path:
        raise ValueError("vertical_export_invalid:path")
    destination = Path(output_path)
    if destination.suffix != ".json":
        raise ValueError("vertical_export_invalid:path")
    allowed_root = (Path.cwd() / "runtime" / "contracts").resolve()
    resolved = destination.resolve()
    try:
        resolved.relative_to(allowed_root)
    except ValueError as exc:
        raise ValueError("vertical_export_invalid:path") from exc
    if resolved.is_dir():
        raise ValueError("vertical_export_invalid:path")
    return destination, resolved


def write_open_interest_and_funding_screen_json(
    *,
    screen_contract: Mapping[str, Any],
    output_path: str | Path = DEFAULT_OPEN_INTEREST_AND_FUNDING_OUTPUT_PATH,
    allow_invalid: bool = False,
) -> Path:
    """Atomically write one validated Open Interest and Funding screen."""
    if not isinstance(screen_contract, Mapping):
        raise ValueError("vertical_export_invalid:screen")
    if type(allow_invalid) is not bool:
        raise ValueError("vertical_export_invalid:allow_invalid")
    quality, schema, screen = (screen_contract.get("quality"), screen_contract.get("schema"),
                               screen_contract.get("screen"))
    if (not isinstance(schema, Mapping)
            or schema.get("id") != "trad_elatin.open_interest_and_funding.screen.v1"
            or schema.get("version") != "1.0.0"
            or not isinstance(screen, Mapping) or screen.get("id") != "open_interest_and_funding"
            or screen.get("family") != "open_interest_and_funding"
            or screen_contract.get("stage") != "screen_contract"
            or tuple(screen_contract) != OPEN_INTEREST_AND_FUNDING_SCREEN_ROOT
            or not isinstance(quality, Mapping)
            or quality.get("status") not in {"ok", "partial", "invalid"}):
        raise ValueError("vertical_export_invalid:screen")
    if quality["status"] == "invalid" and not allow_invalid:
        raise ValueError("vertical_export_invalid:screen_invalid")
    try:
        _validate_open_interest_and_funding_json(screen_contract)
        serialized = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False,
                                sort_keys=False, indent=2) + "\n"
    except (TypeError, ValueError) as exc:
        if str(exc).startswith("vertical_export_invalid:"):
            raise
        raise ValueError("vertical_export_invalid:serialization") from exc
    destination, resolved = _open_interest_and_funding_destination(output_path)
    temporary: Path | None = None
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", prefix=f".{resolved.name}.", suffix=".tmp",
            dir=resolved.parent, delete=False, newline="\n",
        ) as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, resolved)
        return destination
    except Exception as exc:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise ValueError("vertical_export_invalid:write") from exc


def write_long_short_liquidations_screen_json(*, screen_contract: Mapping[str, Any],
                                              output_path: str | Path) -> Path:
    if not isinstance(screen_contract, Mapping):
        raise ValueError("screen_contract must be a mapping")
    if screen_contract.get("family") != "long_short_liquidations":
        raise ValueError("Expected long_short_liquidations family")
    if screen_contract.get("screen_id") != "long_short_liquidations":
        raise ValueError("Expected long_short_liquidations screen_id")
    if screen_contract.get("contract_version") != "0.1" or not isinstance(screen_contract.get("quality"), Mapping):
        raise ValueError("Invalid long_short_liquidations screen contract")
    serialized = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=f".{destination.name}.", suffix=".tmp",
                                         dir=destination.parent, delete=False, newline="\n") as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def export_long_short_liquidations_screen_json(*, vertical_output: Mapping[str, Any],
                                               output_path: str | Path =
                                               "runtime/contracts/long_short_liquidations_screen.json") -> Path:
    screen = vertical_output.get("screen") if isinstance(vertical_output, Mapping) else None
    if not isinstance(screen, Mapping):
        raise ValueError("vertical_output must contain a mapping at 'screen'")
    return write_long_short_liquidations_screen_json(screen_contract=screen, output_path=output_path)


def write_on_chain_miners_screen_json(*, screen_contract: Mapping[str, Any],
                                      output_path: str | Path) -> Path:
    if not isinstance(screen_contract, Mapping):
        raise ValueError("screen_contract must be a mapping")
    schema = screen_contract.get("schema")
    screen = screen_contract.get("screen")
    if not isinstance(schema, Mapping) or schema.get("id") != "trad_elatin.on_chain_miners.screen.v1":
        raise ValueError("Expected on_chain_miners screen.v1 schema")
    if not isinstance(screen, Mapping) or screen.get("id") != "on_chain_miners" or screen.get("family") != "on_chain_miners":
        raise ValueError("Expected on_chain_miners screen identity")
    if screen_contract.get("stage") != "screen_contract" or not isinstance(screen_contract.get("quality"), Mapping):
        raise ValueError("Invalid on_chain_miners screen contract")
    serialized = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=f".{destination.name}.", suffix=".tmp",
                                         dir=destination.parent, delete=False, newline="\n") as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def export_on_chain_miners_screen_json(*, vertical_output: Mapping[str, Any],
                                       output_path: str | Path =
                                       "runtime/contracts/on_chain_miners_screen.json") -> Path:
    screen = vertical_output.get("screen") if isinstance(vertical_output, Mapping) else None
    if not isinstance(screen, Mapping):
        raise ValueError("vertical_output must contain a mapping at 'screen'")
    return write_on_chain_miners_screen_json(screen_contract=screen, output_path=output_path)


def write_etf_exchange_flows_screen_json(*, screen_contract: Mapping[str, Any],
                                         output_path: str | Path) -> Path:
    if not isinstance(screen_contract, Mapping):
        raise ValueError("screen_contract must be a mapping")
    schema = screen_contract.get("schema")
    screen = screen_contract.get("screen")
    if not isinstance(schema, Mapping) or schema.get("id") != "trad_elatin.etf_exchange_flows.screen.v1":
        raise ValueError("Expected etf_exchange_flows screen.v1 schema")
    if (not isinstance(screen, Mapping) or screen.get("id") != "etf_exchange_flows" or
            screen.get("family") != "etf_exchange_flows"):
        raise ValueError("Expected etf_exchange_flows screen identity")
    if (screen_contract.get("stage") != "screen_contract" or screen_contract.get("version") != "0.1" or
            not isinstance(screen_contract.get("quality"), Mapping)):
        raise ValueError("Invalid etf_exchange_flows screen contract")
    serialized = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", prefix=f".{destination.name}.", suffix=".tmp",
                                         dir=destination.parent, delete=False, newline="\n") as handle:
            temporary = Path(handle.name)
            handle.write(serialized)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
        return destination
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def export_etf_exchange_flows_screen_json(*, vertical_output: Mapping[str, Any],
                                          output_path: str | Path =
                                          "runtime/contracts/etf_exchange_flows_screen.json") -> Path:
    screen = vertical_output.get("screen") if isinstance(vertical_output, Mapping) else None
    if not isinstance(screen, Mapping):
        raise ValueError("vertical_output must contain a mapping at 'screen'")
    return write_etf_exchange_flows_screen_json(screen_contract=screen, output_path=output_path)
