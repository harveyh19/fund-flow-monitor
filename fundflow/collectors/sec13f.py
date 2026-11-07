"""SEC Form 13F holdings for the tracked managers (latest two quarters each).

13F shows US-listed long positions (plus listed options) at quarter end,
filed up to 45 days later. It never shows short stock positions.
"""
import os
import time
import xml.etree.ElementTree as ET

import pandas as pd

from .. import config, store

TABLE = "f13_holdings"


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_infotable(xml_bytes, value_in_thousands=False):
    root = ET.fromstring(xml_bytes)
    rows = []
    for el in root.iter():
        if _local(el.tag) != "infoTable":
            continue
        rec = {}
        for child in el.iter():
            name = _local(child.tag)
            if child is el:
                continue
            if name in ("nameOfIssuer", "titleOfClass", "cusip", "value",
                        "sshPrnamt", "sshPrnamtType", "putCall"):
                rec[name] = (child.text or "").strip()
        rows.append(rec)
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    for c in ("putCall", "sshPrnamtType"):
        if c not in df:
            df[c] = ""
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    if value_in_thousands:
        df["value"] *= 1000
    df["sshPrnamt"] = pd.to_numeric(df["sshPrnamt"], errors="coerce")
    df["cusip"] = df["cusip"].str.upper().str.strip()
    df["putCall"] = df["putCall"].fillna("").str.upper()
    # one row per security + put/call (managers split by sub-adviser)
    g = (df.groupby(["cusip", "putCall"], as_index=False)
           .agg(issuer=("nameOfIssuer", "first"), cls=("titleOfClass", "first"),
                value_usd=("value", "sum"), shares=("sshPrnamt", "sum")))
    return g


def _filings(sec, cik):
    r = sec.get(config.SEC_SUBMISSIONS_URL.format(cik=cik))
    r.raise_for_status()
    j = r.json()
    rec = pd.DataFrame(j["filings"]["recent"])
    rec = rec[rec["form"] == "13F-HR"].copy()
    return j.get("name", ""), rec


def _infotable_url(sec, cik, acc):
    base = config.SEC_ARCHIVE_URL.format(cik=cik, acc=acc.replace("-", ""))
    r = sec.get(base + "index.json")
    r.raise_for_status()
    items = r.json()["directory"]["item"]
    xmls = [i["name"] for i in items if i["name"].lower().endswith(".xml")
            and i["name"].lower() != "primary_doc.xml"]
    if not xmls:
        raise ValueError(f"no information table in {acc}")
    # the information table is the largest XML that is not the cover page
    xmls.sort(key=lambda n: -int(next((i.get("size") or 0 for i in items if i["name"] == n), 0) or 0))
    return base + xmls[0]


def collect(sec, quarters=2):
    old = store.read(TABLE)
    have = set(zip(old["cik"].astype(int), old["period"].astype(str))) if not old.empty else set()
    frames, status = [], {"funds": {}, "skipped": {}}
    groups = [("hedge", f) for f in config.HEDGE_FUNDS] + \
             [("multistrat", f) for f in config.MULTISTRAT_FUNDS] + \
             [("large", f) for f in config.LARGE_MANAGERS]
    stale_before = (pd.Timestamp.today() - pd.DateOffset(months=8)).date().isoformat()
    for group, (cik, expect, label) in groups:
        try:
            name, rec = _filings(sec, cik)
            if expect.lower() not in name.lower():
                status["skipped"][label] = f"CIK {cik} is '{name}', expected '{expect}'"
                continue
            rec = rec.sort_values("filingDate", ascending=False)
            rec = rec.drop_duplicates("reportDate", keep="first").head(quarters)
            got = []
            for _, f in rec.iterrows():
                period = str(f["reportDate"])
                if (cik, period) in have:
                    got.append(period)
                    continue
                url = _infotable_url(sec, cik, f["accessionNumber"])
                xml = sec.get(url).content
                thousands = str(f["filingDate"]) < "2023-01-03"
                h = parse_infotable(xml, value_in_thousands=thousands)
                h["cik"], h["manager"], h["group"] = cik, label, group
                h["period"], h["filed"] = period, str(f["filingDate"])
                frames.append(h)
                got.append(period)
            status["funds"][label] = got
            if got and max(got) < stale_before:
                status.setdefault("stale", {})[label] = (
                    f"latest 13F is for {max(got)}; this CIK may have stopped filing")
        except Exception as e:
            status["skipped"][label] = str(e)[:200]
    if frames:
        new = pd.concat(frames, ignore_index=True)
        store.upsert(TABLE, new, ["cik", "period", "cusip", "putCall"])
    # keep only the 3 most recent periods per manager to bound repo size
    allh = store.read(TABLE)
    if not allh.empty:
        keep = (allh[["cik", "period"]].drop_duplicates()
                .sort_values("period", ascending=False).groupby("cik").head(3))
        allh = allh.merge(keep, on=["cik", "period"])
        store.write(TABLE, allh)
    status["ok"] = bool(status["funds"])
    return status


# --- CUSIP -> ticker via OpenFIGI (free; faster with OPENFIGI_API_KEY) -------

def map_cusips(sess, cusips):
    cache = store.read("cusip_map", dtype=str)
    known = set(cache["cusip"]) if not cache.empty else set()
    todo = [c for c in sorted(set(cusips)) if c and c not in known]
    key = os.environ.get("OPENFIGI_API_KEY")
    batch, gap = (100, 0.25) if key else (10, 2.5)  # stay under free rate limits
    headers = {"Content-Type": "application/json"}
    if key:
        headers["X-OPENFIGI-APIKEY"] = key
    out, fails = [], 0
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        body = [{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in chunk]
        r = sess.post(config.OPENFIGI_URL, json=body, headers=headers, timeout=60)
        if r.status_code == 429:
            time.sleep(60)
            r = sess.post(config.OPENFIGI_URL, json=body, headers=headers, timeout=60)
        if r.status_code != 200:
            fails += 1
            if fails > 5:
                break
            continue
        for c, res in zip(chunk, r.json()):
            data = res.get("data") or []
            t = data[0].get("ticker", "") if data else ""
            out.append({"cusip": c, "ticker": t})
        time.sleep(gap)
    if out:
        cache = store.upsert("cusip_map", pd.DataFrame(out), ["cusip"])
    return cache, {"mapped_now": len(out), "unmapped_left": max(0, len(todo) - len(out))}
