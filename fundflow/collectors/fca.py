"""FCA (UK) aggregate net short positions, published daily since 13 July 2026.

The FCA does not document column names, so columns are found by keyword.
"""
import io

import pandas as pd

from .. import config, store
from ..util import to_num

TABLE = "fca_ansp"


def _find(cols, *alts):
    low = {c.lower().strip(): c for c in cols}
    for words in alts:
        for lc, c in low.items():
            if all(w in lc for w in words):
                return c
    return None


def parse(text, kind):
    # the file may carry a title line before the header: find the header row
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines[:15]) if "isin" in l.lower()), 0)
    df = pd.read_csv(io.StringIO("\n".join(lines[start:])))
    c_name = _find(df.columns, ("name",), ("company",), ("issuer",))
    c_isin = _find(df.columns, ("isin",))
    c_pct = _find(df.columns, ("aggregate", "%"), ("net short", "%"), ("%",),
                  ("aggregate", "position"), ("position", "size"))
    c_pos_date = _find(df.columns, ("position", "date"), ("latest", "date"))
    c_hist_date = _find(df.columns, ("historic",), ("superseded",), ("became",))
    if not (c_isin and c_pct and c_pos_date):
        raise ValueError(f"FCA {kind}: unrecognised columns {list(df.columns)}")
    out = pd.DataFrame({
        "company": df[c_name].astype(str).str.strip() if c_name else "",
        "isin": df[c_isin].astype(str).str.strip(),
        "pct": to_num(df[c_pct]).values,
        "position_date": pd.to_datetime(df[c_pos_date], dayfirst=True,
                                        errors="coerce").dt.date.astype(str),
        "kind": kind,
    })
    if kind == "historic" and c_hist_date:
        out["historic_from"] = pd.to_datetime(df[c_hist_date], dayfirst=True,
                                              errors="coerce").dt.date.astype(str)
    return out.dropna(subset=["pct"])


def collect(sess):
    status = {"ok": False}
    frames = []
    for url, kind in ((config.FCA_CURRENT_URL, "current"),
                      (config.FCA_HISTORIC_URL, "historic")):
        r = sess.get(url, headers={"Accept": "text/csv,*/*"})
        if r.status_code != 200 or "<html" in r.text[:500].lower():
            status[f"{kind}_error"] = f"HTTP {r.status_code} (site may block automated access)"
            continue
        frames.append(parse(r.text, kind))
    if frames:
        df = pd.concat(frames, ignore_index=True)
        store.upsert(TABLE, df, ["isin", "position_date", "kind"])
        cur = df[df["kind"] == "current"]
        status.update(ok=True, as_of=cur["position_date"].max() if not cur.empty
                      else df["position_date"].max(), rows=len(df))
    return status
