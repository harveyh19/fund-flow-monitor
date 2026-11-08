"""Weekly pipeline: collect every feed, compute signals, export docs/.

    python -m fundflow.run            # normal weekly run
    python -m fundflow.run --only signals   # recompute from stored data
"""
import argparse
import json
import math
import traceback
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, signals, store
from .collectors import cftc, fca, finra, sec13f, sfc, southbound, spdr, universe
from .net import make_session, sec_session

DOCS = Path("docs")


def clean(o):
    """Make numpy / NaN values JSON-safe (NaN -> null)."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def step(status, name, fn):
    try:
        status[name] = fn()
    except Exception as e:
        status[name] = {"ok": False, "error": repr(e)[:400],
                        "trace": traceback.format_exc()[-1200:]}
    print(f"[{name}] {json.dumps(clean(status[name]))[:400]}", flush=True)


def collect_all(status):
    web = make_session()
    sec = sec_session()
    step(status, "sp1500_sectors", lambda: universe.collect_sectors(web))
    step(status, "sec_shares_outstanding", lambda: universe.collect_shares(sec))
    step(status, "finra_short_interest", lambda: finra.collect(web))
    step(status, "sfc_hk_shorts", lambda: sfc.collect(web))
    step(status, "hkex_southbound", lambda: southbound.collect(web))
    step(status, "fca_uk_shorts", lambda: fca.collect(web))
    step(status, "cftc_futures", lambda: cftc.collect(web))
    step(status, "spdr_sector_etfs", lambda: spdr.collect(web))
    step(status, "sec_13f", lambda: sec13f.collect(sec))

    def figi():
        h = store.read("f13_holdings", dtype={"cusip": str})
        if h.empty:
            return {"ok": False, "error": "no 13F holdings"}
        h = h[h["putCall"].fillna("") == ""]
        top = (h[h["group"] != "hedge"].sort_values("value_usd", ascending=False)
               .groupby(["manager", "period"]).head(config.TH["f13_map_top_n"]))
        cusips = pd.concat([h[h["group"] == "hedge"]["cusip"], top["cusip"]]).dropna().unique()
        _, st = sec13f.map_cusips(web, cusips)
        st["ok"] = True
        return st
    step(status, "openfigi_cusip_map", figi)


def export(res):
    DOCS.mkdir(exist_ok=True)
    res = clean(res)
    (DOCS / "signals.json").write_text(json.dumps(res, indent=1))

    def csv(name, rows):
        df = pd.DataFrame(rows or [])
        df.to_csv(DOCS / f"{name}.csv", index=False)

    csv("alerts", res.get("alerts"))
    st = []
    for k, v in (res.get("data_status") or {}).items():
        if isinstance(v, dict):
            st.append({"feed": k, "ok": v.get("ok"), "as_of": v.get("as_of"),
                       "note": v.get("error") or json.dumps({x: y for x, y in v.items()
                                                             if x not in ("ok", "as_of", "trace")})[:300]})
    csv("data_status", st)
    us = res.get("us_short") or {}
    csv("us_market_si", us.get("market_series"))
    csv("us_sector_si", us.get("sectors"))
    csv("us_sector_si_series", us.get("sector_series"))
    csv("us_top_si", us.get("top_si"))
    csv("lookup_us", us.get("lookup"))
    hk = res.get("hk") or {}
    csv("hk_top_shorts", hk.get("top_shorts"))
    csv("hk_short_total", hk.get("short_total_series"))
    csv("lookup_hk_shorts", hk.get("shorts"))
    csv("southbound_buys", hk.get("sb_buys_value") or hk.get("sb_buys"))
    csv("southbound_sells", hk.get("sb_sells_value") or hk.get("sb_sells"))
    csv("lookup_hk_southbound", hk.get("sb_lookup"))
    csv("southbound_etfs", hk.get("sb_etfs"))
    uk = res.get("uk") or {}
    csv("uk_top_shorts", uk.get("top"))
    csv("lookup_uk", uk.get("lookup"))
    cf = res.get("cftc") or {}
    csv("cftc_latest", cf.get("latest"))
    csv("cftc_series", cf.get("series"))
    ef = res.get("etf_flows") or {}
    csv("etf_flows_latest", ef.get("latest"))
    csv("etf_flows_series", ef.get("series"))
    tf = res.get("thirteen_f") or {}
    for g in ("hedge", "multistrat", "large"):
        r = tf.get(g) or {}
        csv(f"f13_{g}_sector_shift", r.get("sector_shift"))
        csv(f"f13_{g}_top_adds", r.get("top_adds"))
        csv(f"f13_{g}_top_cuts", r.get("top_cuts"))
    hr = tf.get("hedge") or {}
    csv("f13_consensus_new", hr.get("consensus_new"))
    csv("f13_consensus_exit", hr.get("consensus_exit"))
    csv("f13_hedge_by_ticker", hr.get("by_ticker"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["signals"], default=None)
    a = ap.parse_args()
    status = {}
    if a.only != "signals":
        collect_all(status)
    else:
        old = DOCS / "signals.json"
        if old.exists():
            status = json.loads(old.read_text()).get("data_status", {})
    res = signals.build(status)
    export(res)
    n = len(res.get("alerts", []))
    print(f"done: {n} alerts")


if __name__ == "__main__":
    main()
