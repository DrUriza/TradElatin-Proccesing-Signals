from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib         import Path
from typing          import Any

from .prices_ohlcv import run_prices_vertical


DEFAULT_OUTPUT_PATH = Path("runtime/contracts/prices_screen.json")
TIMEFRAME_SECONDS   = {"1m": 60, "5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}


def write_prices_screen_json(*, screen_contract: Mapping[str, Any], output_path: Path) -> Path:
    """Serialize and atomically publish the final Prices screen contract."""
    if screen_contract.get("family") != "prices_ohlcv" or screen_contract.get("screen") != "prices":
        raise ValueError("Expected the final prices_ohlcv Prices screen contract")
    serialized  = json.dumps(screen_contract, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    output_path = Path(output_path)
    temporary   = output_path.with_name(f"{output_path.name}.tmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(output_path)
    return output_path


def export_prices_screen_json(*, vertical_output: Mapping[str, Any], output_path: Path) -> Path:
    """Export only the unwrapped screen member of a completed Prices vertical."""
    screen_contract = vertical_output.get("screen")
    if not isinstance(screen_contract, Mapping):
        raise ValueError("vertical_output must contain a mapping at 'screen'")
    return write_prices_screen_json(screen_contract=screen_contract, output_path=output_path)


class SyntheticPricesFetcher:
    """Deterministic provider-shaped fetcher used only by the explicit CLI flag."""

    def __init__(self, *, start_index: int = 0) -> None:
        self.start_index = start_index

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        params    = kwargs["params"]
        timeframe = str(params["interval"])
        step      = TIMEFRAME_SECONDS[timeframe]
        count     = int(params["limit"])
        offset    = 20.0 if kwargs["endpoint_id"] == "futures_ohlcv" else 0.0
        records   = []
        for index in range(self.start_index, self.start_index + count):
            close = 100.0 + offset + index * 0.25 + (index % 7 - 3) * 0.20
            records.append({"time": (1_699_920_000 + index * step) * 1_000, "open": close - 0.50, "high": close + 1.0,
                            "low": close - 1.0, "close": close, "volume": 1_000.0 + index})
        return {"code": "0", "msg": "success", "data": records}


def _run_synthetic_vertical(mode: str) -> dict[str, Any]:
    common           = {"bootstrap_limit": 120}
    runtime_metadata = {"data_mode": "synthetic", "is_demo": True, "provider": "synthetic_prices_fetcher"}
    bootstrap        = run_prices_vertical(fetcher=SyntheticPricesFetcher(), input_arguments={"requested_mode": "bootstrap", **common},
                                           now_timestamp=1_800_000_000, runtime_metadata=runtime_metadata)
    if mode == "bootstrap":
        return bootstrap
    if mode == "incremental":
        arguments = {"requested_mode": "incremental", "incremental_limits": {"1m": 6, "15m": 6}}
        return run_prices_vertical(fetcher=SyntheticPricesFetcher(start_index=117), input_arguments=arguments,
                                   previous_state=bootstrap, now_timestamp=1_800_000_060, runtime_metadata=runtime_metadata)
    requests = [{"market": market, "timeframe": timeframe, "limit": 120}
                for market in ("spot", "futures") for timeframe in TIMEFRAME_SECONDS]
    return run_prices_vertical(fetcher=SyntheticPricesFetcher(), input_arguments={"requested_mode": "recovery", "recovery_requests": requests},
                               previous_state=bootstrap, now_timestamp=1_800_000_120, runtime_metadata=runtime_metadata)


def _write_debug_bundle(vertical_output: Mapping[str, Any], output_path: Path) -> Path:
    serialized  = json.dumps(vertical_output, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    output_path = Path(output_path)
    temporary   = output_path.with_name(f"{output_path.name}.tmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(output_path)
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export the final Prices screen contract.")
    parser.add_argument("--mode", choices=("bootstrap", "incremental", "recovery"), default="bootstrap")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--debug-output", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    arguments = parser.parse_args(argv)
    if not arguments.synthetic:
        parser.error("a configured live fetcher is not available; use --synthetic")
    vertical_output = _run_synthetic_vertical(arguments.mode)
    export_prices_screen_json(vertical_output=vertical_output, output_path=arguments.output)
    if arguments.debug_output is not None:
        _write_debug_bundle(vertical_output, arguments.debug_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
