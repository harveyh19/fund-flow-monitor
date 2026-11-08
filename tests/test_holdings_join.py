"""Holdings matcher test. All holdings here are made-up examples."""
import importlib.util
from pathlib import Path

import pandas as pd

spec = importlib.util.spec_from_file_location(
    "holdings_join", Path(__file__).parents[1] / "tools" / "holdings_join.py")
hj = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hj)


def test_join_matches_each_market(tmp_path):
    pd.DataFrame([{"code": 5, "name": "STOCK 5", "short_hkd_m": 900.0, "short_pct": 0.5,
                   "chg_pp_1w": 0.02, "pctile_52w": 90, "xs_pctile": 19}]).to_csv(tmp_path / "lookup_hk_shorts.csv", index=False)
    pd.DataFrame([{"code": 5, "name": "STOCK 5", "sb_pct": 8.9, "chg_pp_5d": 0.1, "est_flow_hkd_m": -59, "z": None}]
                 ).to_csv(tmp_path / "lookup_hk_southbound.csv", index=False)
    pd.DataFrame([{"key": "TEST", "symbol": "TEST", "si_pct": 1.12, "si_rise_vs_6wk": 0.06,
                   "si_pctile_1y": 38, "xs_pctile": 20, "days_to_cover": 2.4}]).to_csv(tmp_path / "lookup_us.csv", index=False)
    pd.DataFrame([{"ticker": "XLK", "sector": "Information Technology", "flow_4w_pct_aum": 0.74, "pctile_3y": 66}]
                 ).to_csv(tmp_path / "etf_flows_latest.csv", index=False)
    pd.DataFrame([{"sector": "Information Technology", "si_pct": 2.59, "vs_market_pp": -1.05}]
                 ).to_csv(tmp_path / "us_sector_si.csv", index=False)
    pd.DataFrame([{"feed": "HK short positions", "kind": "stock", "ticker": "0005.HK", "name": "STOCK 5",
                   "detail": "planted"}]).to_csv(tmp_path / "alerts.csv", index=False)
    h = pd.DataFrame([
        {"market": "HK", "ticker": "0005", "name": "Example HK", "shares": "100", "monitor_link": ""},
        {"market": "US", "ticker": "TEST", "name": "Example US", "shares": "100", "monitor_link": ""},
        {"market": "LSE-UCITS", "ticker": "ETF1", "name": "Example ETF", "shares": "100",
         "monitor_link": "XLK flows + Information Technology short interest"},
        {"market": "KR", "ticker": "000001", "name": "Example KR", "shares": "100", "monitor_link": "not covered"},
    ])
    rows, hits = hj.join(h, tmp_path)
    by = rows.set_index("ticker")
    assert by.loc["0005.HK", "short_pct"] == 0.5 and by.loc["0005.HK", "alert_count"] == 1
    assert "Southbound holds 8.90%" in by.loc["0005.HK", "summary"]
    assert by.loc["TEST", "short_pct"] == 1.12
    assert "XLK" in by.loc["ETF1", "summary"] and "-1.05 pp vs market" in by.loc["ETF1", "summary"]
    assert by.loc["000001", "summary"] == "not covered by the free feeds"
    assert list(hits["holding"]) == ["0005.HK"]
