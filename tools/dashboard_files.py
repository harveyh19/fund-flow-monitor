"""Turn docs/ (public market signals) and the private holdings output into the
JSON files the dashboard loads, one file per dashboard dataset.

    python tools/dashboard_files.py --docs docs --private out --dest stage
"""
import argparse
import json
import math
from pathlib import Path

import pandas as pd

TABLES = {  # dataset id: (docs csv, max rows or None)
    "alerts": ("alerts", None),
    "us_market_si": ("us_market_si", None),
    "us_sector_si": ("us_sector_si", None),
    "us_top_si": ("us_top_si", 25),
    "hk_top_shorts": ("hk_top_shorts", 20),
    "southbound_buys": ("southbound_buys", 15),
    "southbound_sells": ("southbound_sells", 15),
    "southbound_etfs": ("southbound_etfs", 10),
    "uk_top_shorts": ("uk_top_shorts", 20),
    "cftc_latest": ("cftc_latest", None),
    "etf_flows_latest": ("etf_flows_latest", None),
    "f13_consensus_new": ("f13_consensus_new", 15),
    "f13_consensus_exit": ("f13_consensus_exit", 15),
    "f13_hedge_sector_shift": ("f13_hedge_sector_shift", None),
    "data_status": ("data_status", None),
}


def _clean(o):
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, float) and (math.isnan(o) or math.isinf(o)):
        return None
    return o


def _rows(path, limit=None):
    if not path.exists() or path.stat().st_size < 3:
        return []
    df = pd.read_csv(path)
    if limit:
        df = df.head(limit)
    return _clean(json.loads(df.to_json(orient="records")))


def build(docs, private, dest):
    docs, dest = Path(docs), Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    out = {}
    for ds, (name, limit) in TABLES.items():
        rows = _rows(docs / f"{name}.csv", limit)
        if ds == "alerts":
            for i, r in enumerate(rows):
                r["id"] = f"a{i + 1:03d}"
                r["ticker"] = r.get("ticker") or ""
        if ds == "data_status":
            for r in rows:
                r["ok"] = "yes" if r.get("ok") in (True, "True", "true") else "no"
                r["as_of"] = r.get("as_of") or ""
        out[ds] = rows

    sig = json.loads((docs / "signals.json").read_text())
    us = sig.get("us_short") or {}
    hk = sig.get("hk") or {}
    tf = (sig.get("thirteen_f") or {}).get("hedge") or {}
    mk = us.get("market") or {}
    out["headline"] = [_clean({
        "generated_at": sig.get("generated_at"),
        "us_avg_short_pct": mk.get("avg_si_pct"),
        "us_avg_short_pctile_3y": mk.get("pctile_3y"),
        "us_short_as_of": mk.get("date") or us.get("as_of"),
        "hk_short_as_of": hk.get("short_as_of"),
        "sb_from": (hk.get("sb_period") or {}).get("from"),
        "sb_to": (hk.get("sb_period") or {}).get("to"),
        "sb_net_flow_hkd_bn": hk.get("sb_est_net_flow_hkd_bn"),
        "sb_etf_net_flow_hkd_bn": hk.get("sb_etf_net_flow_hkd_bn"),
        "f13_period": tf.get("period"),
        "f13_prev_period": tf.get("prev_period"),
        "f13_funds": len(tf.get("funds") or []),
        "uk_as_of": (sig.get("uk") or {}).get("as_of"),
        "cftc_as_of": (sig.get("cftc") or {}).get("as_of"),
    })]

    if private:
        p = Path(private) / "holdings_signals.json"
        out["holdings"] = _clean(json.loads(p.read_text())) if p.exists() else []
        for r in out["holdings"]:
            r["alerts"] = r.get("alerts") or ""
    for ds, rows in out.items():
        (dest / f"{ds}.json").write_text(json.dumps(rows, ensure_ascii=False))
    return {k: len(v) for k, v in out.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--private", default=None)
    ap.add_argument("--dest", default="stage")
    a = ap.parse_args()
    print(json.dumps(build(a.docs, a.private, a.dest)))


if __name__ == "__main__":
    main()
