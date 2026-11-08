"""Turn stored history into alerts and dashboard tables.

Each alert carries `evidence`:
  strong  - short interest (Boehmer, Jones & Zhang 2008; Rapach,
            Ringgenberg & Zhou 2016)
  good    - Southbound flows (Ding, Song, Bian & Zhang 2025)
  context - 13F, futures positioning, ETF flows: shown, not signals
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

from . import config, store
from .util import norm_ticker, pct_rank, zscore

TH = config.TH


def _r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# ---------------------------------------------------------------- US shorts

def us_short(alerts):
    si = store.read("finra_si", dtype={"key": str})
    if si.empty:
        return {}
    sp = store.read("sp1500", dtype={"key": str})
    sh = store.read("sec_shares", dtype={"key": str})
    if not sh.empty:
        si = si.merge(sh[["key", "shares_out", "multi_class"]], on="key", how="left")
    else:
        si["shares_out"], si["multi_class"] = np.nan, False
    si["si_pct"] = si["short_shares"] / si["shares_out"] * 100
    si.loc[(si["si_pct"] > 100) | (si["si_pct"] <= 0), "si_pct"] = np.nan
    dates = sorted(si["settlement_date"].unique())
    latest = dates[-1]
    out = {"as_of": latest}

    if not sp.empty:
        si = si.merge(sp[["key", "sector", "index", "company"]], on="key", how="left")
    else:
        si["sector"], si["index"], si["company"] = np.nan, np.nan, np.nan
    spx = si[si["sector"].notna()]

    # --- market-wide index: equal-weighted average short % of S&P 1500 names
    mk = (spx.dropna(subset=["si_pct"])
          .assign(si_w=lambda d: d["si_pct"].clip(upper=50))
          .groupby("settlement_date")["si_w"].agg(["mean", "count"]).reset_index())
    mk = mk[mk["count"] >= 300]  # need broad coverage for the date to count
    series = mk.rename(columns={"settlement_date": "date", "mean": "avg_si_pct",
                                "count": "stocks"})
    if len(series) > 1:
        last = series.iloc[-1]
        hist = series["avg_si_pct"].iloc[:-1].tail(72)  # ~3 years of settlements
        p = pct_rank(hist, last["avg_si_pct"])
        out["market"] = {"date": last["date"], "avg_si_pct": _r(last["avg_si_pct"]),
                         "pctile_3y": _r(p, 0), "obs": int(len(hist))}
        if len(hist) >= 24 and p >= TH["us_market_pctile"]:
            alerts.append(dict(feed="US short interest", market="US", kind="market",
                               name="S&P 1500 average short interest",
                               detail=f"{last['avg_si_pct']:.2f}% of shares, near a 3-year high "
                                      f"(percentile {p:.0f})",
                               evidence="strong", date=last["date"]))
    out["market_series"] = series.round(3).to_dict("records")

    # --- sectors
    sec = (spx.dropna(subset=["shares_out"])
           .groupby(["settlement_date", "sector"])[["short_shares", "shares_out"]].sum()
           .reset_index())
    sec["si_pct"] = sec["short_shares"] / sec["shares_out"] * 100
    tot = sec.groupby("settlement_date")[["short_shares", "shares_out"]].sum()
    mkt = (tot["short_shares"] / tot["shares_out"] * 100).rename("mkt_pct")
    sec = sec.merge(mkt, left_on="settlement_date", right_index=True)
    sec["rel_pp"] = sec["si_pct"] - sec["mkt_pct"]  # sector vs whole S&P 1500
    rows = []
    for s, g in sec.groupby("sector"):
        g = g.sort_values("settlement_date")
        if g["settlement_date"].iloc[-1] != latest:
            continue
        cur, rel = g["si_pct"].iloc[-1], g["rel_pp"].iloc[-1]
        hist = g["si_pct"].iloc[:-1].tail(72)
        rhist = g["rel_pp"].iloc[:-1].tail(72)
        prev = g["si_pct"].iloc[-2] if len(g) > 1 else np.nan
        p, rp = pct_rank(hist, cur), pct_rank(rhist, rel)
        rows.append({"sector": s, "si_pct": _r(cur), "chg_pp": _r(cur - prev),
                     "pctile_3y": _r(p, 0), "vs_market_pp": _r(rel),
                     "vs_market_pctile_3y": _r(rp, 0), "obs": len(hist)})
        if len(rhist) >= 24 and rp >= TH["sector_si_pctile"]:
            alerts.append(dict(feed="US short interest", market="US", kind="sector",
                               name=s, sector=s,
                               detail=f"Sector short interest {cur:.2f}% of shares, {rel:+.2f} pp versus the "
                                      f"whole S&P 1500: the most shorted relative to the market in 3 years "
                                      f"(percentile {rp:.0f})",
                               evidence="strong", date=latest))
    out["sectors"] = sorted(rows, key=lambda r: -(r["vs_market_pctile_3y"] or 0))
    out["sector_series"] = sec[["settlement_date", "sector", "si_pct"]].round(3).to_dict("records")

    # --- single stocks
    piv = si.pivot_table(index="key", columns="settlement_date", values="si_pct")
    dtc = si.pivot_table(index="key", columns="settlement_date", values="days_to_cover")
    cur = si[si["settlement_date"] == latest].set_index("key")
    xs = cur[cur["sector"].apply(lambda v: isinstance(v, str))]["si_pct"].dropna()
    look, top = [], []
    for k, r in cur.iterrows():
        rec = {"key": k, "symbol": r["symbol"], "name": r.get("company") if isinstance(r.get("company"), str) else r["name"],
               "sector": r.get("sector") if isinstance(r.get("sector"), str) else "",
               "si_pct": _r(r["si_pct"]), "days_to_cover": _r(r["days_to_cover"]),
               "short_shares": int(r["short_shares"]) if pd.notna(r["short_shares"]) else None}
        if k in piv.index:
            h = piv.loc[k].dropna()
            h = h[h.index < latest].tail(24)
            rec["si_pctile_1y"] = _r(pct_rank(h, r["si_pct"]), 0) if len(h) >= 12 else None
            back = h.iloc[-3] if len(h) >= 3 else np.nan
            rec["si_rise_vs_6wk"] = _r(r["si_pct"] / back - 1) if back and back > 0 else None
        if k in dtc.index:
            hd = dtc.loc[k].dropna()
            hd = hd[hd.index < latest].tail(24)
            rec["dtc_pctile_1y"] = _r(pct_rank(hd, r["days_to_cover"]), 0) if len(hd) >= 12 else None
        rec["xs_pctile"] = _r(pct_rank(xs, r["si_pct"]), 0) if pd.notna(r["si_pct"]) else None
        look.append(rec)
        in_sp = isinstance(r.get("sector"), str)
        if in_sp and rec.get("si_pctile_1y") is not None and \
           rec["si_pctile_1y"] >= TH["us_si_pctile"] and (rec["si_pct"] or 0) >= TH["us_si_min_pct"] and \
           (rec.get("xs_pctile") or 0) >= TH["us_si_xs_pctile"] and \
           (rec.get("si_rise_vs_6wk") or 0) >= TH["us_si_min_rise"]:
            alerts.append(dict(feed="US short interest", market="US", kind="stock",
                               ticker=r["symbol"], name=rec["name"], sector=rec["sector"],
                               detail=f"Short interest {rec['si_pct']:.1f}% of shares (1-year high zone, among the "
                                      f"most-shorted {max(1, 100 - rec['xs_pctile']):.0f}% of the S&P 1500, "
                                      f"up {rec['si_rise_vs_6wk']*100:.0f}% in ~6 weeks); "
                                      f"{rec['days_to_cover']} days to cover",
                               evidence="strong", date=latest,
                               score=rec["si_pct"]))
        if in_sp and rec["si_pct"] is not None:
            top.append(rec)
    out["top_si"] = sorted(top, key=lambda r: -r["si_pct"])[:30]
    out["lookup"] = look
    return out


# --------------------------------------------------------------- HK shorts

def hk(alerts):
    sfc = store.read("sfc_shorts")
    sb = store.read("southbound")
    out = {}
    issued = pd.Series(dtype=float)
    price = pd.Series(dtype=float)
    if not sb.empty:
        last_sb = sb[sb["date"] == sb["date"].max()]
        issued = last_sb.set_index("code")["issued_shares"]
    if not sfc.empty:
        latest = sfc["date"].max()
        out["short_as_of"] = latest
        cur = sfc[sfc["date"] == latest].set_index("code")
        price = (cur["short_hkd"] / cur["short_shares"]).replace([np.inf], np.nan)
        sfc["issued"] = sfc["code"].map(issued)
        sfc["short_pct"] = sfc["short_shares"] / sfc["issued"] * 100
        piv = sfc.pivot_table(index="code", columns="date", values="short_pct")
        pivs = sfc.pivot_table(index="code", columns="date", values="short_shares")
        rows = []
        lv = sfc[sfc["date"] == latest].set_index("code")["short_pct"].dropna()
        for code, r in cur.iterrows():
            rec = {"code": int(code), "name": r["name"], "short_hkd_m": _r(r["short_hkd"] / 1e6, 1),
                   "short_pct": None, "chg_pp_1w": None, "pctile_52w": None}
            sp_ = piv.loc[code].dropna() if code in piv.index else pd.Series(dtype=float)
            if latest in sp_.index:
                v = sp_[latest]
                h = sp_[sp_.index < latest].tail(52)
                rec["short_pct"] = _r(v, 3)
                if len(h):
                    rec["chg_pp_1w"] = _r(v - h.iloc[-1], 3)
                if len(h) >= 26:
                    rec["pctile_52w"] = _r(pct_rank(h, v), 0)
            elif code in pivs.index:  # no issued-share count: rank raw shares
                s = pivs.loc[code].dropna()
                h = s[s.index < latest].tail(52)
                if len(h) >= 26:
                    rec["pctile_52w"] = _r(pct_rank(h, r["short_shares"]), 0)
            rec["xs_pctile"] = _r(pct_rank(lv, rec["short_pct"]), 0) if rec["short_pct"] is not None else None
            rows.append(rec)
            big = (r["short_hkd"] or 0) >= TH["hk_short_min_hkd"]
            hit_p = rec["pctile_52w"] is not None and rec["pctile_52w"] >= TH["hk_short_pctile"] and \
                rec["xs_pctile"] is not None and rec["xs_pctile"] >= TH["hk_short_xs_pctile"]
            hit_j = rec["chg_pp_1w"] is not None and rec["chg_pp_1w"] >= TH["hk_short_jump_pp"]
            if big and (hit_p or hit_j):
                why = []
                if hit_p:
                    why.append(f"52-week high zone (percentile {rec['pctile_52w']:.0f}) and among the "
                               f"most-shorted HK stocks (top {max(1, 100 - rec['xs_pctile']):.0f}%)")
                if hit_j:
                    why.append(f"up {rec['chg_pp_1w']:.2f} pp in a week")
                pct = f"{rec['short_pct']:.2f}% of shares, " if rec["short_pct"] is not None else ""
                alerts.append(dict(feed="HK short positions", market="HK", kind="stock",
                                   ticker=f"{int(code):04d}.HK", name=r["name"],
                                   detail=f"Short {pct}HK${rec['short_hkd_m']:,.0f}m; " + "; ".join(why),
                                   evidence="strong", date=latest,
                                   score=rec["short_pct"] or 0))
        out["shorts"] = rows
        out["top_shorts"] = sorted([x for x in rows if x["short_pct"] is not None],
                                   key=lambda x: -x["short_pct"])[:30]
        tot = sfc.groupby("date")["short_hkd"].sum().reset_index()
        out["short_total_series"] = [{"date": d, "short_hkd_bn": _r(v / 1e9, 2)}
                                     for d, v in zip(tot["date"], tot["short_hkd"])]

    # ---------------------------------------------------- Southbound
    if not sb.empty:
        days = sorted(sb["date"].unique())
        L = days[-1]
        out["southbound_as_of"] = L
        anchor = (date.fromisoformat(L) - timedelta(days=7)).isoformat()
        earlier = [d for d in days if d <= anchor]
        if earlier and earlier[-1] >= (date.fromisoformat(L) - timedelta(days=12)).isoformat():
            P = earlier[-1]  # one calendar week (5 trading days) earlier
            a = sb[sb["date"] == L].set_index("code")
            b = sb[sb["date"] == P].set_index("code")
            j = a[["name", "sb_pct", "sb_shares"]].join(b[["sb_pct", "sb_shares"]], rsuffix="_prev", how="inner")
            j["chg_pp_5d"] = j["sb_pct"] - j["sb_pct_prev"]
            j["chg_shares"] = j["sb_shares"] - j["sb_shares_prev"]
            j["price"] = j.index.map(price)
            j["est_flow_hkd_m"] = j["chg_shares"] * j["price"] / 1e6
            # history of Friday-to-Friday changes for z-scores
            sbw = sb.copy()
            sbw["d"] = pd.to_datetime(sbw["date"])
            iso = sbw["d"].dt.isocalendar()
            sbw["iy"], sbw["iw"] = iso.year.astype(int), iso.week.astype(int)
            wk = sbw.sort_values("d").groupby(["code", "iy", "iw"]).tail(1)
            wk = wk.sort_values("d")
            wk["wchg"] = wk.groupby("code")["sb_pct"].diff()
            zs = {}
            for code, g in wk.groupby("code"):
                h = g["wchg"].dropna().iloc[:-1]
                if len(h) >= 20 and code in j.index:
                    zs[code] = zscore(h, j.loc[code, "chg_pp_5d"])
            j["z"] = j.index.map(zs)
            j = j.reset_index()
            cols = ["code", "name", "sb_pct", "chg_pp_5d", "est_flow_hkd_m", "z"]
            n = TH["sb_top_n"]
            out["sb_period"] = {"from": P, "to": L}
            out["sb_buys"] = j.sort_values("chg_pp_5d", ascending=False)[cols].head(n).round(3).to_dict("records")
            out["sb_sells"] = j.sort_values("chg_pp_5d")[cols].head(n).round(3).to_dict("records")
            vj = j.dropna(subset=["est_flow_hkd_m"])
            out["sb_buys_value"] = vj.sort_values("est_flow_hkd_m", ascending=False)[cols].head(n).round(3).to_dict("records")
            out["sb_sells_value"] = vj.sort_values("est_flow_hkd_m")[cols].head(n).round(3).to_dict("records")
            out["sb_est_net_flow_hkd_bn"] = _r(vj["est_flow_hkd_m"].sum() / 1e3, 2)
            out["sb_lookup"] = j[cols].round(3).to_dict("records")
            for _, r in j.iterrows():
                if pd.notna(r["z"]) and abs(r["z"]) >= TH["sb_z"] and \
                   pd.notna(r["est_flow_hkd_m"]) and abs(r["est_flow_hkd_m"]) >= TH["sb_min_flow_hkd_m"]:
                    side = "buying" if r["chg_pp_5d"] > 0 else "selling"
                    alerts.append(dict(feed="Southbound", market="HK", kind="stock",
                                       ticker=f"{int(r['code']):04d}.HK", name=r["name"],
                                       detail=f"Unusual mainland {side}: {r['chg_pp_5d']:+.2f} pp of shares in 5 days "
                                              f"(~HK${r['est_flow_hkd_m']:,.0f}m, z={r['z']:.1f}); now holds {r['sb_pct']:.2f}%",
                                       evidence="good", date=L, score=abs(r["z"])))
    return out


# ------------------------------------------------------------------- UK

def uk(alerts):
    df = store.read("fca_ansp")
    if df.empty:
        return {}
    df = df.dropna(subset=["position_date"]).sort_values("position_date")
    latest = df["position_date"].max()
    week_ago = (date.fromisoformat(latest) - timedelta(days=7)).isoformat()
    rows = []
    for isin, g in df.groupby("isin"):
        now = g[g["kind"] == "current"]
        if now.empty:
            continue
        v = now.sort_values("position_date")["pct"].iloc[-1]
        prev_g = g[g["position_date"] <= week_ago]
        prev = prev_g["pct"].iloc[-1] if not prev_g.empty else np.nan
        name = now["company"].iloc[-1]
        rec = {"isin": isin, "company": name, "pct": _r(v), "pct_week_ago": _r(prev),
               "chg_pp": _r(v - prev) if not np.isnan(prev) else None,
               "as_of": now["position_date"].max()}
        rows.append(rec)
        crossed = [lv for lv in TH["uk_levels"] if v >= lv and (np.isnan(prev) or prev < lv)]
        jump = rec["chg_pp"] is not None and rec["chg_pp"] >= TH["uk_jump_pp"] and v >= TH["uk_jump_min_pct"]
        if crossed or jump:
            why = [f"crossed {max(crossed):.0f}%"] if crossed else []
            if jump:
                why.append(f"up {rec['chg_pp']:.2f} pp in a week")
            alerts.append(dict(feed="UK short positions", market="UK", kind="stock",
                               ticker=isin, name=name,
                               detail=f"Aggregate short {v:.2f}% of shares; " + "; ".join(why),
                               evidence="strong", date=rec["as_of"], score=v))
    rows.sort(key=lambda r: -(r["pct"] or 0))
    always = [r for r in rows if r["isin"] in config.UK_ALWAYS]
    for isin, nm in config.UK_ALWAYS.items():
        if not any(r["isin"] == isin for r in rows):
            always.append({"isin": isin, "company": nm, "pct": None,
                           "note": "below the 0.2% reporting threshold or not published"})
    return {"as_of": latest, "top": rows[:30], "watch": always, "lookup": rows}


# ----------------------------------------------------------------- CFTC

def cftc():
    df = store.read("cftc_tff")
    if df.empty:
        return {}
    df["lev_net_pct_oi"] = (df["lev_long"] - df["lev_short"]) / df["oi"] * 100
    df["am_net_pct_oi"] = (df["am_long"] - df["am_short"]) / df["oi"] * 100
    rows = []
    for label, g in df.sort_values("date").groupby("label"):
        last = g.iloc[-1]
        h = g.iloc[:-1].tail(156)
        lp = pct_rank(h["lev_net_pct_oi"], last["lev_net_pct_oi"])
        ap = pct_rank(h["am_net_pct_oi"], last["am_net_pct_oi"])
        flag = ""
        if lp >= TH["cftc_pctile_hi"]:
            flag = "hedge funds unusually long"
        elif lp <= TH["cftc_pctile_lo"]:
            flag = "hedge funds unusually short"
        rows.append({"market": label, "date": last["date"],
                     "lev_funds_net_pct_oi": _r(last["lev_net_pct_oi"], 1),
                     "lev_pctile_3y": _r(lp, 0),
                     "asset_mgr_net_pct_oi": _r(last["am_net_pct_oi"], 1),
                     "am_pctile_3y": _r(ap, 0),
                     "flag": flag, "evidence": "context"})
    series = df[["date", "label", "lev_net_pct_oi", "am_net_pct_oi"]].rename(columns={"label": "market"})
    return {"as_of": df["date"].max(), "latest": rows,
            "series": series.round(2).to_dict("records")}


# ------------------------------------------------------------ ETF flows

def etf(alerts):
    df = store.read("etf_flows_daily")
    if df.empty:
        return {}
    df["d"] = pd.to_datetime(df["date"])
    rows, series = [], []
    for t, g in df.groupby("ticker"):
        w = (g.set_index("d").resample("W-FRI")
             .agg({"flow_usd": "sum", "aum_usd": "last"}).dropna())
        w["flow_4w"] = w["flow_usd"].rolling(4).sum()
        w["flow_4w_pct_aum"] = w["flow_4w"] / w["aum_usd"] * 100
        w = w.dropna()
        if w.empty:
            continue
        last = w.iloc[-1]
        h = w["flow_4w_pct_aum"].iloc[:-1].tail(156)
        p = pct_rank(h, last["flow_4w_pct_aum"])
        rec = {"ticker": t, "sector": config.SPDR_ETFS.get(t, t),
               "week_ending": w.index[-1].date().isoformat(),
               "flow_1w_usd_m": _r(last["flow_usd"] / 1e6, 0),
               "flow_4w_usd_m": _r(last["flow_4w"] / 1e6, 0),
               "flow_4w_pct_aum": _r(last["flow_4w_pct_aum"], 2),
               "pctile_3y": _r(p, 0), "aum_usd_bn": _r(last["aum_usd"] / 1e9, 1)}
        rows.append(rec)
        if len(h) >= 52 and (p >= TH["etf_pctile_hi"] or p <= TH["etf_pctile_lo"]):
            side = "inflows" if p >= TH["etf_pctile_hi"] else "outflows"
            alerts.append(dict(feed="Sector ETF flows", market="US", kind="sector",
                               ticker=t, name=rec["sector"], sector=rec["sector"],
                               detail=f"Unusual 4-week {side}: {rec['flow_4w_usd_m']:+,.0f}m USD "
                                      f"({rec['flow_4w_pct_aum']:+.2f}% of fund), percentile {p:.0f}",
                               evidence="context", date=rec["week_ending"]))
        s = w.tail(52).reset_index()
        for _, r in s.iterrows():
            series.append({"week_ending": r["d"].date().isoformat(), "ticker": t,
                           "sector": config.SPDR_ETFS.get(t, t),
                           "flow_usd_m": _r(r["flow_usd"] / 1e6, 0)})
    return {"latest": sorted(rows, key=lambda r: -(r["flow_4w_pct_aum"] or 0)), "series": series}


# ------------------------------------------------------------------- 13F

def _qprev(period):
    p = pd.Timestamp(period)
    return (p - pd.offsets.QuarterEnd(1)).date().isoformat()


def thirteen_f(alerts):
    h = store.read("f13_holdings", dtype={"cusip": str, "putCall": str})
    if h.empty:
        return {}
    h["putCall"] = h["putCall"].fillna("")
    h = h[h["putCall"] == ""]  # stock positions only
    cmap = store.read("cusip_map", dtype=str)
    sp = store.read("sp1500", dtype={"key": str})
    if not cmap.empty:
        h = h.merge(cmap, on="cusip", how="left")
    else:
        h["ticker"] = ""
    h["key"] = h["ticker"].map(norm_ticker)
    if not sp.empty:
        h = h.merge(sp[["key", "sector"]], on="key", how="left")
    h["sector"] = h.get("sector", pd.Series(index=h.index, dtype=object))
    out = {}
    for group in ("hedge", "multistrat", "large"):
        g = h[h["group"] == group]
        if g.empty:
            continue
        latest_by_fund = g.groupby("manager")["period"].max()
        counts = latest_by_fund.value_counts()
        target = None
        for per in sorted(counts.index, reverse=True):
            if counts[per] >= 0.5 * len(latest_by_fund):
                target = per
                break
        if target is None:
            continue
        prev = _qprev(target)
        both = [m for m, d in g.groupby("manager") if {target, prev} <= set(d["period"])]
        gg = g[g["manager"].isin(both)]
        cur, old = gg[gg["period"] == target], gg[gg["period"] == prev]
        res = {"period": target, "prev_period": prev, "funds": sorted(both),
               "funds_pending": sorted(set(latest_by_fund.index) - set(both))}
        # sector weights over holdings we could map to an S&P 1500 sector;
        # coverage says what share of the portfolio value that is
        def weights(d):
            mapped = d.dropna(subset=["sector"])
            w = mapped.groupby("sector")["value_usd"].sum()
            return w / w.sum() * 100, mapped["value_usd"].sum() / d["value_usd"].sum() * 100
        (wc, cov_c), (wo, _) = weights(cur), weights(old)
        res["sector_coverage_pct"] = _r(cov_c, 1)
        sec = pd.DataFrame({"weight_pct": wc, "prev_weight_pct": wo}).fillna(0)
        sec["chg_pp"] = sec["weight_pct"] - sec["prev_weight_pct"]
        res["sector_shift"] = sec.reset_index().rename(columns={"index": "sector"}) \
            .sort_values("chg_pp", ascending=False).round(2).to_dict("records")
        # share-count changes valued at current price
        a = cur.groupby(["manager", "cusip"]).agg(shares=("shares", "sum"), value=("value_usd", "sum"),
                                                  issuer=("issuer", "first"), ticker=("ticker", "first"),
                                                  sector=("sector", "first"))
        b = old.groupby(["manager", "cusip"]).agg(shares_prev=("shares", "sum"), value_prev=("value_usd", "sum"),
                                                  issuer_p=("issuer", "first"), ticker_p=("ticker", "first"),
                                                  sector_p=("sector", "first"))
        m = a.join(b, how="outer").reset_index()
        for c in ("issuer", "ticker", "sector"):
            m[c] = m[c].fillna(m[f"{c}_p"])
        m[["shares", "value", "shares_prev", "value_prev"]] = m[["shares", "value", "shares_prev", "value_prev"]].fillna(0)
        px = np.where(m["shares"] > 0, m["value"] / m["shares"].replace(0, np.nan),
                      m["value_prev"] / m["shares_prev"].replace(0, np.nan))
        m["flow_usd"] = (m["shares"] - m["shares_prev"]) * px
        # position size as % of each fund's portfolio, now and last quarter
        tot_now = m.groupby("manager")["value"].transform("sum")
        tot_old = m.groupby("manager")["value_prev"].transform("sum")
        m["w_now"] = m["value"] / tot_now * 100
        m["w_prev"] = m["value_prev"] / tot_old * 100
        mw = TH["f13_min_weight"]
        # a filer whose reported book jumped or collapsed >5x changed how it
        # files (new entity, fund transfer) - its "new" lines are not purchases
        ratio = (tot_now / tot_old.replace(0, np.nan))
        restructured = (ratio > 5) | (ratio < 0.2) | ratio.isna()
        res["restructured_filers"] = sorted(m.loc[restructured, "manager"].unique())
        m["new"] = (m["shares_prev"] == 0) & (m["shares"] > 0) & (m["w_now"] >= mw) & ~restructured
        m["exit"] = (m["shares_prev"] > 0) & (m["shares"] == 0) & (m["w_prev"] >= mw) & ~restructured
        m["sector"] = m["sector"].fillna("Other / not in S&P 1500")
        agg = m.groupby("cusip").agg(issuer=("issuer", "first"), ticker=("ticker", "first"),
                                     sector=("sector", "first"), funds_new=("new", "sum"),
                                     funds_exit=("exit", "sum"), net_flow_usd=("flow_usd", "sum"),
                                     holders_now=("shares", lambda s: int((s > 0).sum())))
        agg["net_flow_usd_m"] = (agg["net_flow_usd"] / 1e6).round(0)
        agg["ticker"] = agg["ticker"].fillna("").astype(str)
        agg["issuer"] = agg["issuer"].fillna("").astype(str)
        agg = agg.drop(columns="net_flow_usd").reset_index()
        n = TH["f13_consensus_n"]
        if group == "hedge":
            res["consensus_new"] = agg[agg["funds_new"] >= n].sort_values("funds_new", ascending=False).head(25).to_dict("records")
            res["consensus_exit"] = agg[agg["funds_exit"] >= n].sort_values("funds_exit", ascending=False).head(25).to_dict("records")
            names_new = m[m["new"]].groupby("cusip")["manager"].apply(lambda s: ", ".join(sorted(s)))
            names_exit = m[m["exit"]].groupby("cusip")["manager"].apply(lambda s: ", ".join(sorted(s)))
            for r in res["consensus_new"]:
                r["who"] = names_new.get(r["cusip"], "")
                alerts.append(dict(feed="13F (hedge funds)", market="US", kind="stock",
                                   ticker=r["ticker"] or r["cusip"], name=r["issuer"], sector=r["sector"],
                                   detail=f"{r['funds_new']} stock-picking hedge funds opened new positions (>=0.25% of fund) in "
                                          f"{target[:7]} quarter ({r['who']})",
                                   evidence="context", date=target))
            for r in res["consensus_exit"]:
                r["who"] = names_exit.get(r["cusip"], "")
                alerts.append(dict(feed="13F (hedge funds)", market="US", kind="stock",
                                   ticker=r["ticker"] or r["cusip"], name=r["issuer"], sector=r["sector"],
                                   detail=f"{r['funds_exit']} stock-picking hedge funds sold out of positions in "
                                          f"{target[:7]} quarter ({r['who']})",
                                   evidence="context", date=target))
        res["top_adds"] = agg.sort_values("net_flow_usd_m", ascending=False).head(20).to_dict("records")
        res["top_cuts"] = agg.sort_values("net_flow_usd_m").head(20).to_dict("records")
        res["by_ticker"] = agg[agg["ticker"].fillna("") != ""][["ticker", "issuer", "holders_now", "funds_new",
                                                                 "funds_exit", "net_flow_usd_m"]].to_dict("records")
        out[group] = res
    return out


# ------------------------------------------------------------------ main

def build(status):
    alerts = []
    res = {"generated_at": pd.Timestamp.now("UTC").isoformat(timespec="minutes"),
           "data_status": status}
    for name, fn in (("us_short", lambda: us_short(alerts)), ("hk", lambda: hk(alerts)),
                     ("uk", lambda: uk(alerts)), ("cftc", cftc),
                     ("etf_flows", lambda: etf(alerts)), ("thirteen_f", lambda: thirteen_f(alerts))):
        try:
            res[name] = fn()
        except Exception as e:  # one broken feed must not sink the rest
            res[name] = {}
            res["data_status"].setdefault("signals_errors", {})[name] = repr(e)[:300]
    order = {"strong": 0, "good": 1, "context": 2}
    def _score(a):
        v = a.get("score")
        return 0.0 if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)
    alerts.sort(key=lambda a: (order.get(a["evidence"], 3), -_score(a)))
    res["alerts"] = alerts
    return res
