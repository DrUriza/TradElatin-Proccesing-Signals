"""Generate the ETF exchange-flow synthetic demo screen through the full pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from processing_signals.main.main_pipeline import run_main_pipeline
from processing_signals.runtime.etf_exchange_flows import (
    ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP,
    EtfExchangeFlowsSyntheticFetcher,
)

DEFAULT_OUTPUT = Path("runtime/contracts/etf_exchange_flows_screen.json")


def generate_etf_exchange_flows_screen(*, output_path: str | Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    destination = Path(output_path)
    fetcher = EtfExchangeFlowsSyntheticFetcher()
    screen = run_main_pipeline(enabled_families=("etf_exchange_flows",), screens_only=True,
        family_arguments={"etf_exchange_flows": {
            "fetcher": fetcher,
            "now_timestamp": ETF_EXCHANGE_FLOWS_SYNTHETIC_TIMESTAMP,
            "input_arguments": {"requested_mode": "bootstrap", "exchange_scope": "all_exchange",
                "include_secondary": True, "data_mode": "synthetic", "is_demo": True},
            "contract_arguments": {"selected_range": "30d"},
            "publish_screen": True,
            "output_path": destination,
        }})["etf_exchange_flows"]
    with destination.open("r", encoding="utf-8") as handle:
        loaded = json.load(handle)
    if loaded != screen:
        raise RuntimeError("published ETF screen does not match pipeline output")
    if (loaded.get("schema", {}).get("id") != "trad_elatin.etf_exchange_flows.screen.v1" or
            loaded.get("screen", {}).get("family") != "etf_exchange_flows" or
            loaded.get("stage") != "screen_contract" or loaded.get("data_mode") != "synthetic" or
            loaded.get("is_demo") is not True or loaded.get("range_selector", {}).get("selected") != "30d"):
        raise RuntimeError("published ETF screen identity is invalid")
    for field in ("kpis", "charts", "tables", "classification_states", "provenance", "quality"):
        if not isinstance(loaded.get(field), dict):
            raise RuntimeError(f"published ETF screen is missing {field}")
    if not any(chart.get("points") for chart in loaded["charts"].values() if isinstance(chart, dict)):
        raise RuntimeError("published ETF screen has no chart points")
    if not loaded["tables"].get("etf_funds", {}).get("rows"):
        raise RuntimeError("published ETF screen has no fund rows")
    json.dumps(loaded, ensure_ascii=False, allow_nan=False)
    return screen


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)
    screen = generate_etf_exchange_flows_screen(output_path=arguments.output)
    context = screen.get("context", {})
    print(json.dumps({"output": str(arguments.output), "generated_at": context.get("generated_at"),
        "data_as_of": context.get("data_as_of"), "quality": screen.get("quality", {}).get("status")},
        ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
