"""Reference data: S&P 1500 tickers with GICS sectors, SEC tickers and
shares outstanding (to turn short interest into % of shares)."""
import io
from datetime import date

import pandas as pd

from .. import config, store
from ..util import norm_ticker


def _sector_table(html):
    for t in pd.read_html(io.StringIO(html)):
        cols = [str(c) for c in t.columns]
        sym = next((c for c in cols if c.lower() in ("symbol", "ticker symbol", "ticker")), None)
        sec = next((c for c in cols if "gics sector" in c.lower()), None)
        if sym is None:
            sym = next((c for c in cols if "symbol" in c.lower() or "ticker" in c.lower()), None)
        if sec is None:
            sec = next((c for c in cols if "sector" in c.lower()), None)
        name = next((c for c in cols if c.lower() in ("security", "company")), None)
        if sym and sec and len(t) > 100:
            return pd.DataFrame({"ticker": t[sym].astype(str).str.strip(),
                                 "company": t[name].astype(str) if name else "",
                                 "sector": t[sec].astype(str).str.strip()})
    raise ValueError("no constituents table with symbol + sector")


def collect_sectors(sess):
    frames, errors = [], {}
    for idx, url in config.WIKI_SP_PAGES.items():
        try:
            r = sess.get(url)
            r.raise_for_status()
            t = _sector_table(r.text)
            t["index"] = idx
            frames.append(t)
        except Exception as e:
            errors[idx] = str(e)[:200]
    if not frames:
        return {"ok": False, "errors": errors}
    df = pd.concat(frames, ignore_index=True)
    df["key"] = df["ticker"].map(norm_ticker)
    df = df.drop_duplicates("key")
    store.write("sp1500", df)
    return {"ok": True, "rows": len(df), "errors": errors,
            "by_index": df["index"].value_counts().to_dict()}


def _quarters_back(n, today=None):
    today = today or date.today()
    y, q = today.year, (today.month - 1) // 3 + 1
    out = []
    for _ in range(n):
        out.append(f"CY{y}Q{q}I")
        y, q = (y - 1, 4) if q == 1 else (y, q - 1)
    return out


def collect_shares(sec):
    """Latest reported shares outstanding per company from SEC XBRL frames."""
    r = sec.get(config.SEC_TICKERS_URL)
    r.raise_for_status()
    tick = pd.DataFrame(r.json().values())
    tick["key"] = tick["ticker"].map(norm_ticker)
    frames = []
    for period in _quarters_back(5):
        resp = sec.get(config.SEC_FRAMES_URL.format(period=period))
        if resp.status_code != 200:
            continue
        d = pd.DataFrame(resp.json().get("data", []))
        if not d.empty:
            frames.append(d[["cik", "end", "val"]])
    if not frames:
        return {"ok": False, "error": "no SEC frames"}
    sh = (pd.concat(frames).sort_values("end")
          .drop_duplicates("cik", keep="last")
          .rename(columns={"val": "shares_out", "end": "shares_as_of"}))
    out = tick.merge(sh, left_on="cik_str", right_on="cik", how="inner")
    # several share classes can map to one CIK: cover-page count is the total,
    # which overstates the denominator for each class. Flag those.
    multi = out.groupby("cik")["key"].transform("count") > 1
    out["multi_class"] = multi
    out = out[["key", "ticker", "title", "cik", "shares_out", "shares_as_of", "multi_class"]]
    store.write("sec_shares", out)
    return {"ok": True, "rows": len(out)}
