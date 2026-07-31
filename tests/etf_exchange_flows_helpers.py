from copy import deepcopy

NOW = 1_740_000_000


def provider_body(provider, endpoint_id, params, timestamp=NOW, *, empty=False):
    if provider == "coinglass":
        rows = {
            "bitcoin_etf_flows": [{"timestamp": timestamp*1000, "flow_usd": 10, "price_usd": 50_000,
                                    "etf_flows": [{"etf_ticker": "GBTC", "flow_usd": -2}]}],
            "bitcoin_etf_list": [{"ticker": "GBTC", "fund_name": "Fund", "shares_outstanding": "10",
                                  "aum_usd": "100.5", "management_fee_percent": "1.5", "asset_details": {}}],
            "bitcoin_etf_net_assets_history": [{"timestamp": timestamp*1000, "net_assets_usd": 100,
                                                 "change_usd": 2, "price_usd": 50_000}],
            "bitcoin_etf_premium_discount_history": [{"timestamp": timestamp*1000, "list": [{"ticker": "GBTC",
                "nav_usd": 10, "market_price_usd": 9, "premium_discount_details": -1}]}],
            "exchange_balance_list": [{"exchange_name": "Coinbase", "total_balance": 100,
                                       "balance_change_1d": None, "balance_change_percent_1d": 0}],
            "exchange_balance_chart": [{"time_list": [timestamp*1000], "price_list": [50_000],
                                         "data_map": {"coinbase": [100]}}],
        }[endpoint_id]
        return {"code": "0", "msg": "success", "data": [] if empty else rows}
    if provider == "cryptoquant":
        field = {"exchange_inflow": "inflow_total", "exchange_outflow": "outflow_total",
                 "exchange_netflow": "netflow_total", "exchange_reserve": "reserve"}[endpoint_id]
        row = {"date": "2025-02-19T21:20:00Z", field: None}
        if endpoint_id in {"exchange_inflow", "exchange_outflow"}:
            prefix = endpoint_id.removeprefix("exchange_")
            row[f"{prefix}_top10"] = 2
            row[f"{prefix}_mean"] = 1
        return {"status": {"code": 200, "message": "success"},
                "result": {"window": params["window"], "data": [] if empty else [row]}}
    value = {"nested": 1} if endpoint_id == "exchange_balance" else 1.5
    return [] if empty else [{"t": timestamp, "v": value}]


class Fetcher:
    def __init__(self, timestamp=NOW, *, empty=False, fail=None):
        self.timestamp, self.empty, self.fail, self.calls = timestamp, empty, fail, []

    def __call__(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        if kwargs["endpoint_id"] == self.fail:
            raise RuntimeError("Authorization secret")
        return provider_body(kwargs["provider"], kwargs["endpoint_id"], kwargs["params"], self.timestamp, empty=self.empty)
