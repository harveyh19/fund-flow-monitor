"""US sector ETF flows from State Street SPDR daily NAV + shares outstanding.

Flow on a day = change in shares outstanding x NAV that day (creations minus
redemptions). Files carry the fund's full daily history.
"""
import io

import pandas as pd

from .. import config, store

TABLE = "etf_flows_daily"


def parse(content, ticker):
    raw = pd.read_excel(io.BytesIO(content), header=None)
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip().str.lower() == "date"]
    if len(hdr) == 0:
        raise ValueError(f"{ticker}: header row 'Date' not found")
    h = hdr[0]
    df = raw.iloc[h + 1:].copy()
    df.columns = [str(c).strip().lower() for c in raw.iloc[h]]
    need = ["date", "nav", "shares outstanding"]
    if not all(c in df.columns for c in need):
        raise ValueError(f"{ticker}: columns {list(df.columns)}")
    df = df[need].rename(columns={"shares outstanding": "shares"})
    as_text = pd.to_datetime(df["date"], format="%d-%b-%Y", errors="coerce")
    df["date"] = as_text.fillna(pd.to_datetime(df["date"], errors="coerce"))
    df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
    df["shares"] = pd.to_numeric(df["shares"], errors="coerce")
    df = df.dropna().sort_values("date")
    df["flow_usd"] = df["shares"].diff() * df["nav"]
    df["aum_usd"] = df["shares"] * df["nav"]
    df["ticker"] = ticker
    df["date"] = df["date"].dt.date.astype(str)
    return df.dropna(subset=["flow_usd"])[["date", "ticker", "nav", "shares",
                                           "flow_usd", "aum_usd"]]


def collect(sess):
    frames, errors = [], {}
    for t in config.SPDR_ETFS:
        try:
            r = sess.get(config.SPDR_URL.format(t=t.lower()))
            r.raise_for_status()
            frames.append(parse(r.content, t))
        except Exception as e:  # keep going; report per fund
            errors[t] = str(e)[:200]
    if not frames:
        return {"ok": False, "errors": errors}
    df = pd.concat(frames, ignore_index=True)
    cutoff = (pd.Timestamp.today() - pd.DateOffset(years=5)).date().isoformat()
    df = df[df["date"] >= cutoff]
    store.write(TABLE, df)  # files hold full history, so replace
    return {"ok": True, "as_of": df["date"].max(), "funds": sorted(df["ticker"].unique()),
            "errors": errors}
