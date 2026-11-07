"""HKEX Stock Connect Southbound shareholding (mainland money in HK stocks).

The page shows the latest day on a plain GET. Earlier days (HKEX keeps one
year) are fetched by re-posting the page's own form with another date.
"""
from datetime import date, timedelta

import pandas as pd
from bs4 import BeautifulSoup

from .. import config, store
from ..util import fridays_back, to_num

TABLE = "southbound"


def parse(html):
    soup = BeautifulSoup(html, "lxml")
    inp = soup.find("input", {"name": "txtShareholdingDate"})
    if inp is None or not inp.get("value"):
        raise ValueError("Southbound page: shareholding date not found")
    day = pd.to_datetime(inp["value"], format="%Y/%m/%d").date().isoformat()
    rows = []
    for tr in soup.select("tbody tr"):
        cells = {}
        for td in tr.find_all("td"):
            cls = " ".join(td.get("class", []))
            body = td.find("div", class_="mobile-list-body")
            if body is not None:
                cells[cls] = body.get_text(strip=True)
        if "col-stock-code" in cells:
            rows.append(cells)
    if not rows:
        raise ValueError("Southbound page: no rows")
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "date": day,
        "code": to_num(df["col-stock-code"]).astype("Int64").values,
        "name": df["col-stock-name"].values,
        "sb_shares": to_num(df["col-shareholding"]).values,
        "sb_pct": to_num(df["col-shareholding-percent"]).values,
    })
    out = out.dropna(subset=["code"]).drop_duplicates("code")
    # implied issued shares lets us turn SFC short shares into % of shares
    out["issued_shares"] = out["sb_shares"] / (out["sb_pct"] / 100.0)
    out.loc[out["sb_pct"] <= 0, "issued_shares"] = float("nan")
    return out


def _form_fields(html):
    soup = BeautifulSoup(html, "lxml")
    fields = {}
    for i in soup.find_all("input"):
        name = i.get("name")
        typ = (i.get("type") or "text").lower()
        if name and typ in ("hidden", "text"):
            fields[name] = i.get("value", "")
        elif name and typ in ("submit", "button") and "search" in name.lower():
            fields[name] = i.get("value", "Search")
    return fields


def fetch_day(sess, base_html, d):
    fields = _form_fields(base_html)
    fields.update({
        "__EVENTTARGET": "btnSearch",
        "__EVENTARGUMENT": "",
        "txtShareholdingDate": d.strftime("%Y/%m/%d"),
        "today": date.today().strftime("%Y%m%d"),
        "sortBy": "stockcode",
        "sortDirection": "asc",
    })
    r = sess.post(config.SOUTHBOUND_URL, data=fields)
    r.raise_for_status()
    df = parse(r.text)
    if df["date"].iloc[0] != d.isoformat():
        return None  # holiday or out of range: HKEX shows another date
    return df


def collect(sess, weeks_back=52, today=None):
    today = today or date.today()
    r = sess.get(config.SOUTHBOUND_URL)
    r.raise_for_status()
    base = r.text
    latest = parse(base)
    frames = [latest]
    old = store.read(TABLE, usecols=["date"])
    have = set(old["date"].astype(str)) if not old.empty else set()
    have.add(latest["date"].iloc[0])
    latest_day = date.fromisoformat(latest["date"].iloc[0])
    # every trading day of the latest 2 weeks (for 5-day changes) ...
    wanted = [latest_day - timedelta(days=i) for i in range(1, 15)]
    # ... plus each Friday (or the day before) for a year of weekly history
    for fri in fridays_back(weeks_back, latest_day):
        wanted += [fri, fri - timedelta(days=1)]
    errors = 0
    done_weeks = {date.fromisoformat(h).isocalendar()[:2] for h in have}
    for d in sorted(set(wanted), reverse=True):
        if d.weekday() >= 5 or d.isoformat() in have or d >= today:
            continue
        wk = d.isocalendar()[:2]
        if d < latest_day - timedelta(days=14) and wk in done_weeks:
            continue
        try:
            df = fetch_day(sess, base, d)
        except Exception:
            errors += 1
            if errors > 10:
                break
            continue
        if df is not None:
            frames.append(df)
            have.add(d.isoformat())
            done_weeks.add(wk)
    store.upsert(TABLE, pd.concat(frames, ignore_index=True), ["date", "code"])
    return {"ok": True, "as_of": latest["date"].iloc[0], "new_days": len(frames),
            "errors": errors}
