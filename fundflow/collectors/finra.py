"""FINRA bi-monthly short interest for all US exchange-listed stocks."""
import io
from datetime import date

import pandas as pd

from .. import config, store
from ..util import finra_candidates, norm_ticker

TABLE = "finra_si"
KEEP = {
    "symbolCode": "symbol",
    "issueName": "name",
    "marketClassCode": "market",
    "currentShortPositionQuantity": "short_shares",
    "averageDailyVolumeQuantity": "adv",
    "daysToCoverQuantity": "days_to_cover",
    "settlementDate": "settlement_date",
}


def parse(text):
    df = pd.read_csv(io.StringIO(text), sep="|", dtype=str)
    missing = [c for c in KEEP if c not in df.columns]
    if missing:
        raise ValueError(f"FINRA file missing columns {missing}")
    df = df[list(KEEP)].rename(columns=KEEP)
    df = df[df["market"].isin(config.FINRA_EXCHANGE_CLASSES)].copy()
    for c in ("short_shares", "adv", "days_to_cover"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["key"] = df["symbol"].map(norm_ticker)
    return df


def _fetch_half(sess, cands, have):
    for d in cands:
        ds = d.isoformat()
        if ds in have:
            return None, ds  # already stored
        r = sess.get(config.FINRA_URL.format(d=d.strftime("%Y%m%d")), timeout=120)
        # header is quoted in newer files and unquoted in older ones
        if r.status_code == 200 and r.text[:40].replace('"', "").startswith("accountingYearMonthNumber"):
            return parse(r.text), ds
    return None, None


def collect(sess, months_back=None, today=None):
    today = today or date.today()
    old = store.read(TABLE, usecols=["settlement_date"])
    have = set(old["settlement_date"].astype(str)) if not old.empty else set()
    if months_back is None:  # backfill 3 years until we have it, then recent months
        months_back = 36 if len(have) < 60 else 3
    frames, got = [], []
    y, m = today.year, today.month
    for _ in range(months_back + 1):
        mid, late = finra_candidates(y, m)
        for cands in (late, mid):
            cands = [d for d in cands if d < today]
            if not cands:
                continue
            df, ds = _fetch_half(sess, cands, have)
            if df is not None:
                frames.append(df)
                got.append(ds)
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    if frames:
        new = pd.concat(frames, ignore_index=True)
        store.upsert(TABLE, new, ["settlement_date", "key"])
    allrows = store.read(TABLE, usecols=["settlement_date"])
    latest = allrows["settlement_date"].max() if not allrows.empty else None
    return {"ok": latest is not None, "as_of": latest, "new_files": sorted(got)}
