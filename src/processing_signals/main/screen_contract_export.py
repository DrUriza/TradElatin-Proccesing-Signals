from __future__ import annotations

from collections.abc import Mapping
import json
import os
from pathlib import Path
import tempfile
from typing import Any


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
