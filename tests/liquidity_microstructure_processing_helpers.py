from copy import deepcopy


def dataset(records=None, *, events=None, status="available", reason=None):
    result = {"status": status, "reason": reason, "incoming_records": len(records or events or []),
              "source_data_as_of": 1_700_000_000, "provenance": {"provider": "coinglass"}, "warnings": [], "errors": []}
    result["events" if events is not None else "records"] = deepcopy(events if events is not None else records or [])
    return result


def liquidity_input(*, mode="bootstrap", reference=1_700_000_000):
    books, depths, whales = {}, {}, []
    for market, offset in (("spot", 0), ("perpetual", 1)):
        records = []
        depth_records = []
        for index, timeframe in enumerate(("1m", "5m", "15m", "1h")):
            timestamp = reference - 100 + index
            records.append({"timestamp": timestamp, "market_type": market, "exchange": "Binance", "symbol": "BTCUSDT", "timeframe": timeframe,
                            "bid_levels": [{"price": 99 + offset, "quantity": 0.6}, {"price": 98 + offset, "quantity": 0.6}],
                            "ask_levels": [{"price": 101 + offset, "quantity": 0.4}, {"price": 102 + offset, "quantity": 0.7}]})
            for range_percent, multiplier in ((1, 1), (5, 2), (10, 3)):
                depth_records.append({"timestamp": timestamp, "market_type": market, "exchange": "Binance", "symbol": "BTCUSDT",
                                      "timeframe": timeframe, "range_percent": range_percent,
                                      "bids_usd": 100 * multiplier, "bids_quantity": 2 * multiplier,
                                      "asks_usd": 120 * multiplier, "asks_quantity": 3 * multiplier})
            if market == "perpetual":
                whales.append({"timestamp": timestamp, "market_type": "perpetual", "exchange": "Binance", "symbol": "BTCUSDT",
                               "timeframe": timeframe, "whale_index_value": float(index)})
        books[market], depths[market] = dataset(records), dataset(depth_records)
    trades = {market: dataset(events=[{"event_id": f"{market}-1", "timestamp": reference, "market_type": market,
                                      "exchange": "Binance", "symbol": "BTCUSDT", "base_asset": "BTC", "side": "buy",
                                      "price": 100.0, "volume_usd": 20_000.0, "provider_channel": "channel",
                                      "configured_min_volume_usd": 10_000.0, "meets_configured_threshold": True}]) for market in ("spot", "perpetual")}
    market = dataset([{"timestamp": reference - 31 * 86400, "asset": "BTC", "price": 90.0, "circulating_supply": 19.0, "market_cap": 1710.0},
                      {"timestamp": reference - 7 * 86400, "asset": "BTC", "price": 95.0, "circulating_supply": 19.0, "market_cap": 1805.0},
                      {"timestamp": reference, "asset": "BTC", "price": 100.0, "circulating_supply": 19.0, "market_cap": 1900.0}])
    return {"family": "liquidity_microstructure", "stage": "input", "mode": mode, "reference_timestamp": reference,
            "execution_timestamp": reference, "context": {"asset": "BTC", "exchange": "Binance"},
            "providers": {"coinglass": {"orderbook": books, "order_depth": depths, "large_trades": trades,
                                          "whale_activity": dataset(sorted(whales, key=lambda row: row["timestamp"])), "market_history": market}},
            "quality": {"status": "ok"}}
