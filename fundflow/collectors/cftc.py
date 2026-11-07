"""CFTC Traders in Financial Futures (futures only) via the Socrata API."""
import re
from datetime import date, timedelta

import pandas as pd

from .. import config, store

TABLE = "cftc_tff"

WANT = {  # our name: regex for the API field name
    "oi": r"^open_interest_all$",
    "am_long": r"^asset_mgr_positions_long",
    "am_short": r"^asset_mgr_positions_short",
    "lev_long": r"^lev_money_positions_long",
    "lev_short": r"^lev_money_positions_short",
    "dealer_long": r"^dealer_positions_long",
    "dealer_short": r"^dealer_positions_short",
}


def _col(cols, pattern):
    for c in cols:
        if re.search(pattern, c):
            return c
    raise ValueError(f"CFTC: no field matching {pattern}")


def shape(rows):
    raw = pd.DataFrame(rows)
    if raw.empty:
        return raw
    cols = list(raw.columns)
    out = pd.DataFrame({
        "date": pd.to_datetime(raw["report_date_as_yyyy_mm_dd"]).dt.date.astype(str),
        "market": raw["market_and_exchange_names"].str.strip(),
    })
    for k, pat in WANT.items():
        out[k] = pd.to_numeric(raw[_col(cols, pat)], errors="coerce")
    picked = []
    for pat, label in config.CFTC_MARKETS:
        m = out[out["market"].str.contains(pat, regex=True)]
        if m.empty:
            continue
        # if several markets match, keep the biggest by latest open interest
        last = m[m["date"] == m["date"].max()]
        best = last.sort_values("oi", ascending=False)["market"].iloc[0]
        sel = m[m["market"] == best].copy()
        sel["label"] = label
        picked.append(sel)
    return pd.concat(picked, ignore_index=True) if picked else pd.DataFrame()


def collect(sess, years_back=4):
    since = (date.today() - timedelta(days=365 * years_back)).isoformat()
    params = {
        "$where": f"report_date_as_yyyy_mm_dd >= '{since}T00:00:00'",
        "$limit": 100000,
        "$order": "report_date_as_yyyy_mm_dd",
    }
    r = sess.get(config.CFTC_URL, params=params)
    r.raise_for_status()
    df = shape(r.json())
    if df.empty:
        return {"ok": False, "error": "no matching markets"}
    store.upsert(TABLE, df, ["date", "label"])
    found = sorted(df["label"].unique())
    missing = [l for _, l in config.CFTC_MARKETS if l not in found]
    return {"ok": True, "as_of": df["date"].max(), "markets": found, "missing": missing}
