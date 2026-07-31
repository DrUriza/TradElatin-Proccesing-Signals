from __future__ import annotations

import argparse
import json
import math
from collections.abc import Mapping, Sequence
from pathlib         import Path
from typing          import Any

from .prices_ohlcv import run_prices_vertical
from .long_short_liquidations import run_long_short_liquidations_vertical
from .on_chain_miners import run_on_chain_miners_vertical
from .etf_exchange_flows import run_etf_exchange_flows_vertical


VERTICAL_FAMILY_HANDLERS      = {"prices_ohlcv": run_prices_vertical,
                                 "long_short_liquidations": run_long_short_liquidations_vertical,
                                 "on_chain_miners": run_on_chain_miners_vertical,
                                 "etf_exchange_flows": run_etf_exchange_flows_vertical}
DEFAULT_OUTPUT_PATH           = Path("runtime/contracts/prices_screen.json")
TIMEFRAME_SECONDS             = {"1m": 60, "5m": 300, "15m": 900, "1h": 3_600, "4h": 14_400, "1d": 86_400}
SYNTHETIC_REFERENCE_TIMESTAMP = 1_749_945_600
SYNTHETIC_SOURCE_RECORDS      = {"1m": 600, "15m": 5_760}


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

    def __init__(self, *, reference_timestamp: int = SYNTHETIC_REFERENCE_TIMESTAMP, seed: int = 17, incremental_offset: int = 0) -> None:
        self.reference_timestamp = int(reference_timestamp)
        self.seed                = int(seed)
        self.incremental_offset  = int(incremental_offset)

    def _close(self, index: int, *, timeframe: str, futures: bool) -> float:
        phase        = self.seed * 0.17 + (0.8 if timeframe == "15m" else 0.0)
        regime_index = ((index - 1) % 600) - 599
        if regime_index < -420:
            regime = (regime_index + 600) * 0.035
        elif regime_index < -300:
            regime = 6.3 + math.sin(regime_index / 8.0 + phase) * 0.7
        elif regime_index < -190:
            regime = 6.3 - (regime_index + 300) * 0.045
        elif regime_index < -80:
            regime = 1.35 + (regime_index + 190) * 0.055
        else:
            regime = 7.4 + math.sin(regime_index / 4.5 + phase) * 1.1
        common     = 100.0 + regime + math.sin(index / 17.0 + phase) * 0.45
        divergence = math.sin(index / 23.0 + phase) * (0.32 if futures else -0.12)
        basis      = 0.18 + math.sin(index / 31.0 + phase) * 0.28 if futures else 0.0
        return common + divergence + basis

    def _records(self, *, timeframe: str, futures: bool, requested_count: int) -> list[dict[str, Any]]:
        interval    = TIMEFRAME_SECONDS[timeframe]
        count       = SYNTHETIC_SOURCE_RECORDS[timeframe] if requested_count >= 100 else requested_count
        last_bucket = (self.reference_timestamp // interval) * interval - interval + self.incremental_offset * interval
        first_index = -count + 1
        records     = []
        for offset, index in enumerate(range(first_index, 1)):
            timestamp    = last_bucket - (count - 1 - offset) * interval
            close        = self._close(index + self.incremental_offset, timeframe=timeframe, futures=futures)
            body         = math.sin((index + self.seed) * 0.73) * (0.28 if timeframe == "1m" else 0.55)
            open_        = close - body
            volatility   = 0.18 + abs(math.sin(index / 11.0 + self.seed)) * (0.32 if timeframe == "1m" else 0.75)
            upper        = volatility * (0.55 + abs(math.sin(index * 0.37)))
            lower        = volatility * (0.55 + abs(math.cos(index * 0.41)))
            volume_cycle = math.sin(index / 13.0 + self.seed * 0.11)
            volume       = (1_400.0 * (1.0 + 0.42 * volume_cycle)) if not futures else (1_500.0 * (1.0 - 0.38 * volume_cycle))
            records.append({"time": timestamp * 1_000, "open": open_, "high": max(open_, close) + upper, "low": min(open_, close) - lower,
                            "close": close, "volume": max(volume, 1.0)})
        return records

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        params    = kwargs["params"]
        timeframe = str(params["interval"])
        futures   = kwargs["endpoint_id"] == "futures_ohlcv"
        records   = self._records(timeframe=timeframe, futures=futures, requested_count=int(params["limit"])) if timeframe in {"1m", "15m"} else []
        return {"code": "0", "msg": "success", "data": records}


def run_main_pipeline(*, enabled_families: Sequence[str] = ("prices_ohlcv",),
                      family_arguments: Mapping[str, Mapping[str, Any]] | None = None,
                      previous_state: Mapping[str, Mapping[str, Any]] | None = None,
                      screens_only: bool = False) -> dict[str, Any]:
    arguments = family_arguments or {}
    previous  = previous_state or {}
    outputs   = {}
    for family in enabled_families:
        handler = VERTICAL_FAMILY_HANDLERS.get(family)
        if handler is None:
            raise ValueError(f"No vertical handler registered for family: {family}")
        family_output  = handler(previous_state=previous.get(family), **dict(arguments.get(family, {})))
        outputs[family] = family_output["screen"] if screens_only else family_output
    return outputs

def _run_synthetic_vertical(mode: str) -> dict[str, Any]:
    common           = {"bootstrap_limit": 120}
    runtime_metadata = {"data_mode": "synthetic", "is_demo": True, "provider": "synthetic_prices_fetcher", "reference_timestamp": SYNTHETIC_REFERENCE_TIMESTAMP, "synthetic_seed": 17}
    bootstrap        = run_main_pipeline(family_arguments={"prices_ohlcv": {"fetcher": SyntheticPricesFetcher(), "input_arguments": {"requested_mode": "bootstrap", **common},
                                                                            "now_timestamp": SYNTHETIC_REFERENCE_TIMESTAMP, "runtime_metadata": runtime_metadata}})["prices_ohlcv"]
    if mode == "bootstrap":
        return bootstrap
    if mode == "incremental":
        arguments = {"requested_mode": "incremental", "incremental_limits": {"1m": 6, "15m": 6}}
        return run_main_pipeline(family_arguments={"prices_ohlcv": {"fetcher": SyntheticPricesFetcher(reference_timestamp=SYNTHETIC_REFERENCE_TIMESTAMP + 900,
                                                                                                      incremental_offset=1), "input_arguments": arguments,
                                          "now_timestamp": SYNTHETIC_REFERENCE_TIMESTAMP + 900, "runtime_metadata": runtime_metadata}},
                                 previous_state={"prices_ohlcv": bootstrap})["prices_ohlcv"]
    requests = [{"market": market, "timeframe": timeframe, "limit": 120}
                for market in ("spot", "futures") for timeframe in TIMEFRAME_SECONDS]
    return run_main_pipeline(family_arguments={"prices_ohlcv": {"fetcher": SyntheticPricesFetcher(),
                                      "input_arguments": {"requested_mode": "recovery", "recovery_requests": requests},
                                      "now_timestamp": SYNTHETIC_REFERENCE_TIMESTAMP, "runtime_metadata": runtime_metadata}},
                             previous_state={"prices_ohlcv": bootstrap})["prices_ohlcv"]


def _write_debug_bundle(vertical_output: Mapping[str, Any], output_path: Path) -> Path:
    serialized  = json.dumps(vertical_output, ensure_ascii=False, allow_nan=False, indent=2, sort_keys=False) + "\n"
    output_path = Path(output_path)
    temporary   = output_path.with_name(f"{output_path.name}.tmp")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary.write_text(serialized, encoding="utf-8", newline="\n")
    temporary.replace(output_path)
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the active main vertical and publish its final screen contract."""
    parser = argparse.ArgumentParser(description="Run the main pipeline and export active screen contracts.")
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
