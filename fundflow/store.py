"""Tiny CSV(.gz) history store under data/."""
import os
from pathlib import Path

import pandas as pd

DATA = Path(os.environ.get("FFM_DATA", "data"))


def path(name):
    return DATA / f"{name}.csv.gz"


def read(name, **kw):
    p = path(name)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, **kw)


def upsert(name, df, keys):
    """Add rows to a stored table; rows with the same keys are replaced."""
    if df is None or df.empty:
        return read(name)
    old = read(name)
    if not old.empty:
        # align dtypes of key columns as strings to avoid 5 vs "5" duplicates
        for k in keys:
            old[k] = old[k].astype(str)
        df = df.copy()
        for k in keys:
            df[k] = df[k].astype(str)
        df = pd.concat([old, df], ignore_index=True)
    df = df.drop_duplicates(subset=keys, keep="last").sort_values(keys)
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(path(name), index=False, compression="gzip")
    return df


def write(name, df):
    DATA.mkdir(parents=True, exist_ok=True)
    df.to_csv(path(name), index=False, compression="gzip")
