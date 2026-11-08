"""Match personal holdings to this week's signals.

Holdings never live in this repository. The weekly digest task exports the
private Google Sheet to a CSV, runs this script, and keeps the output private.

    python tools/holdings_join.py --holdings holdings.csv --docs docs --out out/

Holdings CSV columns: market, ticker, name, shares, broker, monitor_link, notes
(market is HK, US, LSE-UCITS or anything else; monitor_link names the
proxies an ETF is linked to, e.g. "XLK flows + Information Technology short
interest").
"""
import argparse
import json
import math
import re
from pathlib import Path

import pandas as pd

UK_ISIN_FOR_HK = {5: "GB0005405286"}  # HSBC is also listed in London

SECTORS = ["Information Technology", "Financials", "Health Care", "Energy", "Industrials",
           "Consumer Discretionary", "Consumer Staples", "Utilities", "Materials",
           "Real Estate", "Communication Services"]
FUTURES = {
    "s&p 500 futures": "S&P 500 e-mini", "nasdaq": "Nasdaq-100 mini",
    "russell 2000 futures": "Russell 2000 e-mini", "eafe": "MSCI EAFE (developed ex-US)",
    "msci em": "MSCI Emerging Markets", "em futures": "MSCI Emerging Markets",
    "nikkei": "Nikkei 225 (yen)",
}


def _read(docs, name):
    p = Path(docs) / f"{name}.csv"
    if not p.exists() or p.stat().st_size < 3:
        return pd.DataFrame()
    return pd.read_csv(p)


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else f
    except (TypeError, ValueError):
        return None


def _fmt(v, nd=2, sign=False):
    v = _num(v)
    if v is None:
        return "n/a"
    return f"{v:+.{nd}f}" if sign else f"{v:.{nd}f}"


def norm(t):
    return re.sub(r"[^A-Z0-9]", "", str(t).upper())


def join(holdings, docs):
    us = _read(docs, "lookup_us")
    hk_s = _read(docs, "lookup_hk_shorts")
    hk_b = _read(docs, "lookup_hk_southbound")
    uk = _read(docs, "lookup_uk")
    sec = _read(docs, "us_sector_si")
    etf = _read(docs, "etf_flows_latest")
    cftc = _read(docs, "cftc_latest")
    mkt = _read(docs, "us_market_si")
    f13 = _read(docs, "f13_hedge_by_ticker")
    alerts = _read(docs, "alerts")

    rows, hits = [], []
    for _, h in holdings.iterrows():
        market = str(h.get("market", "")).strip().upper()
        tick = str(h.get("ticker", "")).strip()
        rec = {"market": market, "ticker": tick, "name": h.get("name", ""),
               "shares": _num(h.get("shares")), "notes": []}
        my_alerts = []
        if market == "HK":
            code = int(re.sub(r"\D", "", tick) or -1)
            rec["ticker"] = f"{code:04d}.HK"
            s = hk_s[hk_s["code"] == code] if not hk_s.empty else hk_s
            if not s.empty:
                r = s.iloc[0]
                rec.update(short_pct=_num(r.get("short_pct")), short_chg=_num(r.get("chg_pp_1w")),
                           short_pctile_own=_num(r.get("pctile_52w")),
                           short_pctile_market=_num(r.get("xs_pctile")),
                           short_hkd_m=_num(r.get("short_hkd_m")))
                if rec["short_pct"] is not None:
                    rec["notes"].append(f"HK short {_fmt(rec['short_pct'])}% of shares "
                                        f"({_fmt(rec['short_chg'], 2, True)} pp w/w; own-52w pctile "
                                        f"{_fmt(rec['short_pctile_own'], 0)}; market pctile "
                                        f"{_fmt(rec['short_pctile_market'], 0)})")
                else:
                    rec["notes"].append(f"HK short HK${_fmt(rec['short_hkd_m'], 0)}m "
                                        f"(own-52w pctile {_fmt(rec['short_pctile_own'], 0)})")
            b = hk_b[hk_b["code"] == code] if not hk_b.empty else hk_b
            if not b.empty:
                r = b.iloc[0]
                rec.update(sb_pct=_num(r.get("sb_pct")), sb_chg_pp=_num(r.get("chg_pp_5d")),
                           sb_flow_hkd_m=_num(r.get("est_flow_hkd_m")), sb_z=_num(r.get("z")))
                rec["notes"].append(f"Southbound holds {_fmt(rec['sb_pct'])}% "
                                    f"({_fmt(rec['sb_chg_pp'], 2, True)} pp in a week, "
                                    f"~HK${_fmt(rec['sb_flow_hkd_m'], 0, True)}m)")
            isin = UK_ISIN_FOR_HK.get(code)
            if isin and not uk.empty:
                u = uk[uk["isin"] == isin]
                if not u.empty:
                    rec["notes"].append(f"UK aggregate short {_fmt(u.iloc[0]['pct'])}%")
            if not alerts.empty:
                my_alerts = alerts[alerts["ticker"].astype(str) == rec["ticker"]].to_dict("records")
                if isin:
                    my_alerts += alerts[alerts["ticker"].astype(str) == isin].to_dict("records")
        elif market == "US":
            k = norm(tick)
            u = us[us["key"].astype(str) == k] if not us.empty else us
            if not u.empty:
                r = u.iloc[0]
                rec.update(short_pct=_num(r.get("si_pct")), short_chg=_num(r.get("si_rise_vs_6wk")),
                           short_pctile_own=_num(r.get("si_pctile_1y")),
                           short_pctile_market=_num(r.get("xs_pctile")),
                           days_to_cover=_num(r.get("days_to_cover")))
                rise = rec["short_chg"]
                rec["notes"].append(f"US short {_fmt(rec['short_pct'])}% of shares "
                                    f"({'n/a' if rise is None else f'{rise*100:+.0f}%'} vs ~6 weeks ago; "
                                    f"{_fmt(rec['days_to_cover'], 1)} days to cover; own-1y pctile "
                                    f"{_fmt(rec['short_pctile_own'], 0)})")
            f = f13[f13["ticker"].astype(str).map(norm) == k] if not f13.empty else f13
            if not f.empty:
                r = f.iloc[0]
                rec.update(f13_holders=_num(r.get("holders_now")), f13_new=_num(r.get("funds_new")),
                           f13_exit=_num(r.get("funds_exit")), f13_flow_usd_m=_num(r.get("net_flow_usd_m")))
                rec["notes"].append(f"13F stock-pickers: {int(rec['f13_holders'] or 0)} hold, "
                                    f"{int(rec['f13_new'] or 0)} opened, {int(rec['f13_exit'] or 0)} exited, "
                                    f"net ~US${_fmt(rec['f13_flow_usd_m'], 0, True)}m")
            if not alerts.empty:
                my_alerts = alerts[alerts["ticker"].astype(str).map(norm) == k].to_dict("records")
        else:
            link = str(h.get("monitor_link", "") or "")
            low = link.lower()
            for t in re.findall(r"\b(XL[A-Z]{1,3}|SPY)\b", link):
                e = etf[etf["ticker"] == t] if not etf.empty else etf
                if not e.empty:
                    r = e.iloc[0]
                    rec["notes"].append(f"{t} ({r['sector']}) 4-week flow {_fmt(r['flow_4w_pct_aum'], 2, True)}% "
                                        f"of fund (3y pctile {_fmt(r['pctile_3y'], 0)})")
                    if not alerts.empty:
                        my_alerts += alerts[alerts["ticker"].astype(str) == t].to_dict("records")
            for s_name in SECTORS:
                if s_name.lower() in low and "short" in low and not sec.empty:
                    r = sec[sec["sector"] == s_name]
                    if not r.empty:
                        r = r.iloc[0]
                        rec["notes"].append(f"{s_name} short {_fmt(r['si_pct'])}% "
                                            f"({_fmt(r.get('vs_market_pp'), 2, True)} pp vs market)")
                        if not alerts.empty:
                            my_alerts += alerts[(alerts["kind"] == "sector") &
                                                (alerts["name"] == s_name)].to_dict("records")
            if "market short interest" in low and not mkt.empty:
                r = mkt.iloc[-1]
                rec["notes"].append(f"US market average short {_fmt(r['avg_si_pct'])}% of shares")
                if not alerts.empty:
                    my_alerts += alerts[(alerts["kind"] == "market")].to_dict("records")
            for key, label in FUTURES.items():
                if key in low and not cftc.empty:
                    r = cftc[cftc["market"] == label]
                    if not r.empty:
                        r = r.iloc[0]
                        rec["notes"].append(f"{label}: hedge funds net {_fmt(r['lev_funds_net_pct_oi'], 1, True)}% "
                                            f"of OI (3y pctile {_fmt(r['lev_pctile_3y'], 0)})")
            if not rec["notes"]:
                rec["notes"].append("not covered by the free feeds")
        seen = set()
        uniq = []
        for a in my_alerts:
            key = (a.get("feed"), a.get("detail"))
            if key not in seen:
                seen.add(key)
                uniq.append(a)
        rec["alert_count"] = len(uniq)
        rec["alerts"] = " | ".join(f"{a['feed']}: {a['detail']}" for a in uniq)
        rec["summary"] = "; ".join(rec.pop("notes"))
        rows.append(rec)
        for a in uniq:
            hits.append({"holding": rec["ticker"], "holding_name": rec["name"], **a})
    return pd.DataFrame(rows), pd.DataFrame(hits)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--holdings", required=True)
    ap.add_argument("--docs", default="docs")
    ap.add_argument("--out", default="out")
    a = ap.parse_args()
    h = pd.read_csv(a.holdings, dtype=str)
    rows, hits = join(h, a.docs)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rows.to_csv(out / "holdings_signals.csv", index=False)
    hits.to_csv(out / "holdings_alerts.csv", index=False)
    clean = json.loads(rows.to_json(orient="records"))
    (out / "holdings_signals.json").write_text(json.dumps(clean, indent=1))
    (out / "holdings_alerts.json").write_text(hits.to_json(orient="records"))
    print(f"{len(rows)} holdings, {len(hits)} alerts touching them")


if __name__ == "__main__":
    main()
