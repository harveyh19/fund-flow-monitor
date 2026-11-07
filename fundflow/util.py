"""Small shared helpers."""
import re
from datetime import date, timedelta

import numpy as np
import pandas as pd


def norm_ticker(t):
    """BRK.B / BRK-B / BRKB -> BRKB, so FINRA, SEC and Wikipedia tickers join."""
    if t is None or (isinstance(t, float) and np.isnan(t)):
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(t).upper())


def to_num(s):
    """'1,234' / '1.5%' / ' 7 ' -> float (NaN if not a number)."""
    return pd.to_numeric(
        pd.Series(s, dtype="object").astype(str)
        .str.replace(r"[,%\s]", "", regex=True)
        .replace({"": None, "nan": None, "None": None}),
        errors="coerce")


def pct_rank(history, value):
    """Percentile (0-100) of `value` within `history` (inclusive, ties count half)."""
    h = np.asarray(pd.to_numeric(pd.Series(history), errors="coerce").dropna(), dtype=float)
    if h.size == 0 or value is None or np.isnan(value):
        return np.nan
    below = (h < value).sum()
    equal = (h == value).sum()
    return 100.0 * (below + 0.5 * equal) / h.size


def zscore(history, value):
    h = np.asarray(pd.to_numeric(pd.Series(history), errors="coerce").dropna(), dtype=float)
    if h.size < 3 or value is None or np.isnan(value):
        return np.nan
    sd = h.std(ddof=1)
    if sd == 0 or np.isnan(sd):
        return np.nan
    return (value - h.mean()) / sd


def fridays_back(n, today=None):
    """The last n Fridays on or before today, newest first."""
    today = today or date.today()
    d = today - timedelta(days=(today.weekday() - 4) % 7)
    return [d - timedelta(weeks=i) for i in range(n)]


def month_end(y, m):
    nxt = date(y + (m == 12), m % 12 + 1, 1)
    return nxt - timedelta(days=1)


def finra_candidates(y, m):
    """Likely FINRA settlement dates in a month, most likely first.

    FINRA settlement dates are the 15th and the last business day of the
    month (moved earlier for weekends/holidays), so try a few days back.
    """
    mid = [date(y, m, d) for d in (15, 14, 13, 12, 11)]
    end = month_end(y, m)
    late = [end - timedelta(days=i) for i in range(6)]
    keep = lambda ds: [d for d in ds if d.weekday() < 5]
    return keep(mid), keep(late)
