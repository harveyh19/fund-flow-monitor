"""SFC Hong Kong weekly aggregated reportable short positions."""
import io
from datetime import timedelta

import pandas as pd

from .. import config, store
from ..util import fridays_back

TABLE = "sfc_shorts"


def parse(text):
    df = pd.read_csv(io.StringIO(text))
    cols = {c.lower(): c for c in df.columns}

    def pick(*words):
        for lc, c in cols.items():
            if all(w in lc for w in words):
                return c
        raise ValueError(f"SFC file: no column with {words}; got {list(df.columns)}")

    out = pd.DataFrame({
        "date": pd.to_datetime(df[pick("date")], format="%d/%m/%Y").dt.date.astype(str),
        "code": pd.to_numeric(df[pick("stock", "code")], errors="coerce").astype("Int64"),
        "name": df[pick("stock", "name")].astype(str).str.strip(),
        "short_shares": pd.to_numeric(df[pick("short", "shares")], errors="coerce"),
        "short_hkd": pd.to_numeric(df[pick("short", "hk$")], errors="coerce"),
    })
    return out.dropna(subset=["code"])


def collect(sess, weeks_back=56, today=None):
    old = store.read(TABLE, usecols=["date"])
    have = set(old["date"].astype(str)) if not old.empty else set()
    frames = []
    for fri in fridays_back(weeks_back, today):
        # reporting day is the last trading day of the week: try Fri, Thu, Wed
        for d in (fri, fri - timedelta(days=1), fri - timedelta(days=2)):
            if d.isoformat() in have:
                break
            r = sess.get(config.SFC_URL.format(y=d.year, m=d.month, d=d.day))
            if r.status_code == 200 and r.text.lstrip().lower().startswith("date"):
                frames.append(parse(r.text))
                break
    if frames:
        store.upsert(TABLE, pd.concat(frames), ["date", "code"])
    allrows = store.read(TABLE, usecols=["date"])
    latest = allrows["date"].max() if not allrows.empty else None
    return {"ok": latest is not None, "as_of": latest, "new_weeks": len(frames)}
