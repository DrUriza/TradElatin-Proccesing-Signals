from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing          import Any

from .prices_ohlcv_data_raw_extract import (
    BOOTSTRAP_TIMEFRAMES,
    PricesFetcher,
    PricesOhlcvRawExtractor,
)


OHLC_FIELDS = ("open", "high", "low", "close")


def determine_prices_input_mode(
    *,
    existing_contract: Mapping[str, Any] | None = None,
    recovery_requests: Sequence[Mapping[str, Any]] | None = None,
    requested_mode: str | None = None,
) -> str:
    if requested_mode is not None:
        if requested_mode not in {"bootstrap", "incremental", "recovery"}:
            raise ValueError(f"Unsupported Prices input mode: {requested_mode}")
        if requested_mode == "recovery" and not recovery_requests:
            raise ValueError("recovery mode requires recovery_requests")
        return requested_mode
    if recovery_requests:
        return "recovery"
    markets = (existing_contract or {}).get("markets", {})
    for market in ("spot", "futures"):
        timeframes = markets.get(market, {}).get("timeframes", {}) if isinstance(markets, Mapping) else {}
        if not all(timeframes.get(timeframe, {}).get("records") for timeframe in BOOTSTRAP_TIMEFRAMES):
            return "bootstrap"
    return "incremental"


def unwrap_coinglass_ohlcv(response: Mapping[str, Any] | Sequence[Any] | None) -> list[Any]:
    if response is None:
        return []
    if isinstance(response, Sequence) and not isinstance(response, (str, bytes, bytearray)):
        return list(response)
    if not isinstance(response, Mapping):
        raise ValueError("CoinGlass OHLC response must be a mapping or sequence")
    code = response.get("code")
    if code not in (None, 0, "0", 200, "200"):
        raise ValueError(f"CoinGlass OHLC request failed: {response.get('msg') or code}")
    data: Any = response.get("data", [])
    while isinstance(data, Mapping):
        for key in ("list", "rows", "items", "data"):
            if key in data:
                data = data[key]
                break
        else:
            return []
    return list(data) if isinstance(data, Sequence) and not isinstance(data, (str, bytes, bytearray)) else []


def normalize_ohlcv_record(record: Mapping[str, Any] | Sequence[Any]) -> dict[str, float | int]:
    if isinstance(record, Mapping):
        timestamp = record.get("timestamp", record.get("time", record.get("t")))
        values    = {field: record.get(field) for field in OHLC_FIELDS}
        volume    = record.get("volume_usd", record.get("volume", record.get("vol", 0.0)))
    elif isinstance(record, Sequence) and not isinstance(record, (str, bytes, bytearray)):
        if len(record) < 5:
            raise ValueError("OHLC sequence requires timestamp, open, high, low and close")
        timestamp = record[0]
        values    = dict(zip(OHLC_FIELDS, record[1:5], strict=True))
        volume    = record[5] if len(record) > 5 else 0.0
    else:
        raise ValueError("OHLC record must be a mapping or sequence")

    if timestamp is None or any(values[field] is None for field in OHLC_FIELDS):
        raise ValueError("OHLC record is missing timestamp or price fields")
    normalized_timestamp = int(float(timestamp))
    if normalized_timestamp > 100_000_000_000:
        normalized_timestamp //= 1000

    normalized = {
        "timestamp": normalized_timestamp,
        **{field: float(values[field]) for field in OHLC_FIELDS},
        "volume_usd": float(volume or 0.0),
    }
    if normalized["high"] < max(normalized["open"], normalized["close"], normalized["low"]):
        raise ValueError("OHLC high is below another price field")
    if normalized["low"] > min(normalized["open"], normalized["close"], normalized["high"]):
        raise ValueError("OHLC low is above another price field")
    return normalized


def upsert_ohlcv_records(
    existing_records: Sequence[Mapping[str, Any]],
    incoming_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_timestamp = {int(record["timestamp"]): dict(record) for record in existing_records}
    by_timestamp.update({int(record["timestamp"]): dict(record) for record in incoming_records})
    return [by_timestamp[timestamp] for timestamp in sorted(by_timestamp)]


def preprocess_market_response(
    *,
    raw_market: Mapping[str, Any],
    existing_market: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    output_timeframes: dict[str, dict[str, Any]] = {}
    existing_timeframes = (existing_market or {}).get("timeframes", {})
    for timeframe, raw_timeframe in raw_market.get("timeframes", {}).items():
        warnings: list[str] = []
        incoming: list[dict[str, Any]] = []
        if raw_timeframe.get("status") == "ok":
            try:
                for index, record in enumerate(unwrap_coinglass_ohlcv(raw_timeframe.get("response"))):
                    try:
                        incoming.append(normalize_ohlcv_record(record))
                    except (TypeError, ValueError) as exc:
                        warnings.append(f"record[{index}]: {exc}")
            except ValueError as exc:
                warnings.append(str(exc))
        else:
            warnings.append(str(raw_timeframe.get("error") or "request_failed"))

        previous = existing_timeframes.get(timeframe, {}).get("records", [])
        output_timeframes[str(timeframe)] = {
            "incoming_records": incoming,
            "records": upsert_ohlcv_records(previous, incoming),
            "warnings": warnings,
        }

    for timeframe, previous_payload in existing_timeframes.items():
        output_timeframes.setdefault(str(timeframe), dict(previous_payload))

    return {
        "provider": raw_market.get("provider", "coinglass"),
        "endpoint_id": raw_market.get("endpoint_id"),
        "timeframes": output_timeframes,
    }


def align_spot_and_futures(
    spot_records: Sequence[Mapping[str, Any]],
    futures_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    spot    = {int(record["timestamp"]): dict(record) for record in spot_records}
    futures = {int(record["timestamp"]): dict(record) for record in futures_records}
    common  = sorted(spot.keys() & futures.keys())
    return {
        "pairs": [(spot[timestamp], futures[timestamp]) for timestamp in common],
        "missing_spot_timestamps": sorted(futures.keys() - spot.keys()),
        "missing_futures_timestamps": sorted(spot.keys() - futures.keys()),
    }


def build_general_price_records(
    spot_records: Sequence[Mapping[str, Any]],
    futures_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    aligned = align_spot_and_futures(spot_records, futures_records)
    records = []
    for spot, futures in aligned["pairs"]:
        spot_volume    = float(spot.get("volume_usd", 0.0) or 0.0)
        futures_volume = float(futures.get("volume_usd", 0.0) or 0.0)
        records.append(
            {
                "timestamp": int(spot["timestamp"]),
                **{
                    field: (float(spot[field]) + float(futures[field])) / 2.0
                    for field in OHLC_FIELDS
                },
                "spot_volume_usd": spot_volume,
                "futures_volume_usd": futures_volume,
                "combined_volume_usd": spot_volume + futures_volume,
                "construction": "spot_futures_arithmetic_mean",
            }
        )

    unavailable = [
        {"timestamp": timestamp, "general_status": "unavailable", "reason": "missing_spot_candle"}
        for timestamp in aligned["missing_spot_timestamps"]
    ] + [
        {"timestamp": timestamp, "general_status": "unavailable", "reason": "missing_futures_candle"}
        for timestamp in aligned["missing_futures_timestamps"]
    ]
    unavailable.sort(key=lambda item: item["timestamp"])
    return {"records": records, "unavailable_records": unavailable}


def evaluate_prices_input_quality(markets: Mapping[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    errors: list[str] = []
    statuses: dict[str, str] = {}
    for market in ("spot", "futures", "general"):
        timeframes      = markets.get(market, {}).get("timeframes", {})
        has_records     = bool(timeframes) and all(payload.get("records") for payload in timeframes.values())
        has_unavailable = any(payload.get("unavailable_records") for payload in timeframes.values())
        statuses[market] = "ok" if has_records and not has_unavailable else "partial"
        for timeframe, payload in timeframes.items():
            for warning in payload.get("warnings", []):
                warnings.append(f"{market}/{timeframe}: {warning}")
            unavailable = payload.get("unavailable_records", [])
            if unavailable:
                warnings.append(f"{market}/{timeframe}: {len(unavailable)} unsynchronized timestamps")
    recovery_required = any(status != "ok" for status in statuses.values())
    return {
        **statuses,
        "recovery_required": recovery_required,
        "warnings": warnings,
        "errors": errors,
    }


class PricesOhlcvInputPreprocessor:
    """Orchestrate normalization, persistence merge, General and quality."""

    def __init__(
        self,
        *,
        raw_extractor: PricesOhlcvRawExtractor,
        existing_contract: Mapping[str, Any] | None = None,
    ) -> None:
        self.raw_extractor     = raw_extractor
        self.existing_contract = dict(existing_contract or {})

    def determine_mode(
        self,
        *,
        requested_mode: str | None = None,
        recovery_requests: Sequence[Mapping[str, Any]] | None = None,
    ) -> str:
        return determine_prices_input_mode(
            existing_contract=self.existing_contract,
            recovery_requests=recovery_requests,
            requested_mode=requested_mode,
        )

    @staticmethod
    def unwrap_response(response: Mapping[str, Any] | Sequence[Any] | None) -> list[Any]:
        return unwrap_coinglass_ohlcv(response)

    @staticmethod
    def normalize_record(record: Mapping[str, Any] | Sequence[Any]) -> dict[str, float | int]:
        return normalize_ohlcv_record(record)

    @staticmethod
    def upsert_records(
        existing_records: Sequence[Mapping[str, Any]],
        incoming_records: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return upsert_ohlcv_records(existing_records, incoming_records)

    @staticmethod
    def align_markets(
        spot_records: Sequence[Mapping[str, Any]],
        futures_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return align_spot_and_futures(spot_records, futures_records)

    @staticmethod
    def build_general(
        spot_records: Sequence[Mapping[str, Any]],
        futures_records: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        return build_general_price_records(spot_records, futures_records)

    @staticmethod
    def evaluate_quality(markets: Mapping[str, Any]) -> dict[str, Any]:
        return evaluate_prices_input_quality(markets)

    def preprocess_market(
        self,
        *,
        market: str,
        raw_market: Mapping[str, Any],
    ) -> dict[str, Any]:
        existing_markets = self.existing_contract.get("markets", {})
        return preprocess_market_response(
            raw_market=raw_market,
            existing_market=existing_markets.get(market, {}),
        )

    def _build_general_timeframes(
        self,
        *,
        spot: Mapping[str, Any],
        futures: Mapping[str, Any],
    ) -> dict[str, dict[str, Any]]:
        general_timeframes: dict[str, dict[str, Any]] = {}
        all_timeframes = sorted(set(spot["timeframes"]) | set(futures["timeframes"]))
        for timeframe in all_timeframes:
            spot_payload    = spot["timeframes"].get(timeframe, {})
            futures_payload = futures["timeframes"].get(timeframe, {})
            complete        = self.build_general(
                spot_payload.get("records", []),
                futures_payload.get("records", []),
            )
            incoming = self.build_general(
                spot_payload.get("incoming_records", []),
                futures_payload.get("incoming_records", []),
            )
            general_timeframes[timeframe] = {
                "incoming_records": incoming["records"],
                "records": complete["records"],
                "unavailable_records": complete["unavailable_records"],
                "warnings": [],
            }
        return general_timeframes

    def run(
        self,
        *,
        requested_mode: str | None = None,
        recovery_requests: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        mode = self.determine_mode(
            requested_mode=requested_mode,
            recovery_requests=recovery_requests,
        )
        raw = self.raw_extractor.run(
            mode=mode,
            recovery_requests=recovery_requests,
        )
        spot    = self.preprocess_market(market="spot", raw_market=raw["raw"]["spot"])
        futures = self.preprocess_market(market="futures", raw_market=raw["raw"]["futures"])
        spot.update({"exchange": self.raw_extractor.exchange, "symbol": self.raw_extractor.symbol})
        futures.update({"exchange": self.raw_extractor.exchange, "symbol": self.raw_extractor.symbol})

        markets = {
            "spot": spot,
            "futures": futures,
            "general": {
                "source": "spot_futures_arithmetic_mean",
                "timeframes": self._build_general_timeframes(spot=spot, futures=futures),
            },
        }
        return {
            "family": "prices_ohlcv",
            "stage": "input",
            "mode": mode,
            "markets": markets,
            "quality": self.evaluate_quality(markets),
        }


def run_prices_ohlcv_input(
    *,
    fetcher: PricesFetcher,
    symbol: str = "BTCUSDT",
    exchange: str = "Binance",
    existing_contract: Mapping[str, Any] | None = None,
    requested_mode: str | None = None,
    recovery_requests: Sequence[Mapping[str, Any]] | None = None,
    bootstrap_limit: int = 500,
    incremental_limits: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Single public family facade backed by the OO implementation."""
    raw_extractor = PricesOhlcvRawExtractor(
        fetcher=fetcher,
        symbol=symbol,
        exchange=exchange,
        bootstrap_limit=bootstrap_limit,
        incremental_limits=incremental_limits,
    )
    preprocessor = PricesOhlcvInputPreprocessor(
        raw_extractor=raw_extractor,
        existing_contract=existing_contract,
    )
    return preprocessor.run(
        requested_mode=requested_mode,
        recovery_requests=recovery_requests,
    )
