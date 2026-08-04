def valid_fetcher(**request):
    endpoint = request["endpoint_id"]
    timestamp = request.get("params", {}).get("end_time", 1_700_000_000_000)
    if endpoint.endswith("large_trades"):
        return []
    if endpoint.endswith("orderbook_heatmap"):
        return {"code": "0", "data": [{"time": timestamp, "bids": [[100, 2]], "asks": [[101, 3]]}]}
    if endpoint.endswith("order_depth"):
        return {"code": 0, "data": [{"time": timestamp, "bids_usd": "200", "bids_quantity": "2",
                                       "asks_usd": "303", "asks_quantity": "3"}]}
    if endpoint == "whale_index":
        return {"code": 0, "data": [{"time": timestamp, "whale_index_value": "-0.25"}]}
    return {"code": 0, "data": [{"timestamp": 1_700_000_000, "price": "30000",
                                    "circulating_supply": "19000000", "market_cap": "570000000000"}]}
