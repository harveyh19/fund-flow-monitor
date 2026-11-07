"""Run the whole pipeline offline against a fake web, with planted signals,
and check the alerts that should fire do fire (and the others don't)."""
import io
import json
import re
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FX = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 7)


class Resp:
    def __init__(self, status=200, text="", content=None, js=None):
        self.status_code, self.text = status, text
        self.content = content if content is not None else text.encode()
        self._js = js

    def json(self):
        return self._js

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def finra_file(d, rng, spike):
    hdr = ('"accountingYearMonthNumber"|"symbolCode"|"issueName"|"issuerServicesGroupExchangeCode"|'
           '"marketClassCode"|"currentShortPositionQuantity"|"previousShortPositionQuantity"|"stockSplitFlag"|'
           '"averageDailyVolumeQuantity"|"daysToCoverQuantity"|"revisionFlag"|"changePercent"|'
           '"changePreviousNumber"|"settlementDate"')
    lines = [hdr]
    for i in range(400):
        t = f"T{i:03d}"
        base = 2.0 + (i % 10) * 0.1
        si = base * (1 + rng.normal(0, 0.03))
        if t == "T007" and spike:
            si = 9.0  # planted short build-up
        shares = int(si / 100 * 1e9)
        lines.append(f'"{d:%Y%m%d}"|"{t}"|"Co {t}"|"A"|"NYSE"|"{shares}"|"0"||"1000000"|"3.1"||"0"|"0"|"{d.isoformat()}"')
    lines.append(f'"{d:%Y%m%d}"|"OTCX"|"Otc co"|"A"|"OTC"|"5"|"0"||"1"|"1"||"0"|"0"|"{d.isoformat()}"')
    return "\n".join(lines)


def sfc_file(d, week_i, n_weeks):
    rows = ["Date,Stock Code,Stock Name,Aggregated Reportable Short Positions (Shares),"
            "Aggregated Reportable Short Positions (HK$)"]
    for code in range(1, 41):
        sh = 1_000_000 * code
        if code == 5 and week_i == 0:
            sh = 60_000_000  # planted: jumps to 2% of 3bn issued shares
        rows.append(f"{d:%d/%m/%Y},{code},STOCK {code},{sh},{sh * 50}")
    return "\n".join(rows)


def southbound_html(d, shift):
    tmpl = (FX / "southbound_sample.html").read_text()
    tmpl = re.sub(r'(<input name="txtShareholdingDate" type="text" value=")[^"]*',
                  r"\g<1>" + d.strftime("%Y/%m/%d"), tmpl)
    row_re = re.compile(r'<tr>\s*<td class="col-stock-code">.*?</tr>', re.S)
    first = row_re.search(tmpl).start()
    tmpl = row_re.sub("", tmpl)
    rows = []
    for code in range(1, 41):
        pct = 5.0 + shift * (3.0 if code == 9 else 0.0)  # planted: code 9 heavy buying
        shares = int(3e9 * pct / 100)
        rows.append(f'<tr><td class="col-stock-code"><div class="mobile-list-heading">Stock Code:</div>'
                    f'<div class="mobile-list-body">{code}</div></td>'
                    f'<td class="col-stock-name"><div class="mobile-list-heading">Name:</div>'
                    f'<div class="mobile-list-body">STOCK {code}</div></td>'
                    f'<td class="col-shareholding"><div class="mobile-list-heading">x</div>'
                    f'<div class="mobile-list-body">{shares:,}</div></td>'
                    f'<td class="col-shareholding-percent"><div class="mobile-list-heading">x</div>'
                    f'<div class="mobile-list-body">{pct:.2f}%</div></td></tr>')
    return tmpl[:first] + "".join(rows) + tmpl[first:]


class FakeWeb:
    def __init__(self):
        self.rng = np.random.default_rng(0)
        self.latest_sb = date(2026, 11, 6)

    def _finra(self, url):
        d = pd.Timestamp(re.search(r"shrt(\d{8})", url).group(1)).date()
        mid = [x for x in (15, 14, 13, 12, 11) if date(d.year, d.month, x).weekday() < 5][0]
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)
        while nxt.weekday() >= 5:
            nxt -= timedelta(days=1)
        if d.day not in (mid, nxt.day) or d > date(2026, 10, 15):
            return Resp(404)
        return Resp(200, finra_file(d, self.rng, spike=(d == date(2026, 10, 15))))

    def get(self, url, **kw):
        if "cdn.finra.org" in url:
            return self._finra(url)
        if "sfc.hk" in url:
            m = re.search(r"Data_(\d{8})\.csv", url)
            d = pd.Timestamp(m.group(1)).date()
            if d.weekday() != 4 or d > TODAY:
                return Resp(404)
            wk = (date(2026, 11, 6) - d).days // 7
            return Resp(200, sfc_file(d, wk, 56))
        if "hkexnews" in url:
            return Resp(200, southbound_html(self.latest_sb, 1))
        if "fca.org.uk" in url:
            if "current" in url:
                return Resp(200, "Name of company,ISIN,Aggregate net short position (%),Position date\n"
                                 "HSBC Holdings plc,GB0005405286,0.31,05/11/2026\n"
                                 "Shorty plc,GB0000000001,2.4,05/11/2026\n")
            return Resp(200, "Name of company,ISIN,Aggregate net short position (%),Position date,"
                             "Date became historic\n"
                             "Shorty plc,GB0000000001,1.6,20/10/2026,04/11/2026\n")
        if "cftc.gov" in url:
            rows = []
            for i in range(200):
                d = date(2026, 11, 3) - timedelta(weeks=i)
                rows.append({"report_date_as_yyyy_mm_dd": d.isoformat() + "T00:00:00.000",
                             "market_and_exchange_names": "E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
                             "open_interest_all": "1000", "asset_mgr_positions_long": "600",
                             "asset_mgr_positions_short": "100",
                             "lev_money_positions_long": str(100 + (300 if i == 0 else i % 50)),
                             "lev_money_positions_short": "300",
                             "dealer_positions_long_all": "1", "dealer_positions_short_all": "1"})
            return Resp(200, js=rows)
        if "ssga.com" in url:
            t = re.search(r"en-(\w+)\.xlsx", url).group(1).upper()
            days = pd.bdate_range(end="2026-11-06", periods=900)
            sh = 1e8 + np.cumsum(np.r_[0, self.rng.normal(0, 2e5, len(days) - 1)])
            if t == "XLE":
                sh[-15:] += np.linspace(0, 3e7, 15)  # planted inflow surge
            rows = [["Fund Name:", t], ["Date", "NAV", "Shares Outstanding", "Total Net Assets"]]
            rows += [[d.strftime("%d-%b-%Y"), 100.0, s, s * 100] for d, s in zip(days[::-1], sh[::-1])]
            buf = io.BytesIO()
            pd.DataFrame(rows).to_excel(buf, header=False, index=False)
            return Resp(200, content=buf.getvalue())
        if "wikipedia" in url:
            body = "".join(f"<tr><td>T{i:03d}</td><td>Co {i}</td><td>{'Energy' if i < 200 else 'Financials'}</td></tr>"
                           for i in range(400))
            return Resp(200, "<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>"
                             + body + "</table>")
        return Resp(404)

    def post(self, url, data=None, json=None, **kw):
        if "hkexnews" in url:
            d = date(*map(int, data["txtShareholdingDate"].split("/")))
            shift = 1 if d >= self.latest_sb - timedelta(days=1) else 0
            return Resp(200, southbound_html(d, shift))
        if "openfigi" in url:
            m = {"037833100": "AAPL", "88160R101": "T007"}
            return Resp(200, js=[{"data": [{"ticker": m.get(b["idValue"], "")}]} for b in json])
        return Resp(404)


class FakeSec:
    def get(self, url, **kw):
        if url.endswith("company_tickers.json"):
            return Resp(200, js={str(i): {"cik_str": 1000 + i, "ticker": f"T{i:03d}", "title": f"Co {i}"}
                                 for i in range(400)})
        if "frames" in url:
            if "CY2026Q3I" not in url:
                return Resp(404)
            return Resp(200, js={"data": [{"cik": 1000 + i, "end": "2026-09-30", "val": 1_000_000_000}
                                          for i in range(400)]})
        m = re.search(r"CIK(\d{10})\.json", url)
        if m:
            cik = int(m.group(1))
            from fundflow import config
            names = {c: n for c, n, _ in config.HEDGE_FUNDS + config.LARGE_MANAGERS}
            if cik not in names or cik > 1200000:  # only a few funds "exist" in the fake
                return Resp(404)
            return Resp(200, js={"name": names[cik].upper() + " LLC", "filings": {"recent": {
                "form": ["13F-HR", "13F-HR"], "reportDate": ["2026-09-30", "2026-06-30"],
                "filingDate": ["2026-11-05", "2026-08-10"],
                "accessionNumber": [f"0000-26-{cik}-Q3", f"0000-26-{cik}-Q2"]}}})
        if url.endswith("index.json"):
            return Resp(200, js={"directory": {"item": [{"name": "primary_doc.xml", "size": "10"},
                                                        {"name": "info.xml", "size": "999"}]}})
        if url.endswith("info.xml"):
            q3 = "Q3" in url
            rows = '<infoTable><nameOfIssuer>APPLE</nameOfIssuer><titleOfClass>COM</titleOfClass>' \
                   '<cusip>037833100</cusip><value>1000</value><shrsOrPrnAmt><sshPrnamt>10</sshPrnamt>' \
                   '</shrsOrPrnAmt></infoTable>'
            if q3:  # every fund opens T007 in Q3 -> consensus new position
                rows += '<infoTable><nameOfIssuer>CO 7</nameOfIssuer><titleOfClass>COM</titleOfClass>' \
                        '<cusip>88160R101</cusip><value>500</value><shrsOrPrnAmt><sshPrnamt>50</sshPrnamt>' \
                        '</shrsOrPrnAmt></infoTable>'
            return Resp(200, content=f"<informationTable>{rows}</informationTable>".encode())
        return Resp(404)


@pytest.fixture
def run_pipeline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("FFM_DATA", str(tmp_path / "data"))
    import importlib
    from fundflow import store
    importlib.reload(store)
    from fundflow import signals, run
    from fundflow.collectors import finra, sfc, southbound, fca, cftc, spdr, universe, sec13f
    for mod in (signals, run, finra, sfc, southbound, fca, cftc, spdr, universe, sec13f):
        importlib.reload(mod)
    monkeypatch.setattr(run, "make_session", lambda *a, **k: FakeWeb())
    monkeypatch.setattr(run, "sec_session", lambda *a, **k: FakeSec())
    monkeypatch.setattr(sec13f.time, "sleep", lambda s: None)


    class FixedDate(date):
        @classmethod
        def today(cls):
            return TODAY
    for mod in (finra, southbound, cftc, universe):
        monkeypatch.setattr(mod, "date", FixedDate)
    import fundflow.util as util
    monkeypatch.setattr(util, "date", FixedDate)
    monkeypatch.setattr("sys.argv", ["run"])
    run.main()
    return json.loads((tmp_path / "docs" / "signals.json").read_text()), tmp_path


def test_pipeline_end_to_end(run_pipeline):
    res, root = run_pipeline
    st = res["data_status"]
    for feed in ("sp1500_sectors", "sec_shares_outstanding", "finra_short_interest", "sfc_hk_shorts",
                 "hkex_southbound", "fca_uk_shorts", "cftc_futures", "spdr_sector_etfs", "sec_13f"):
        assert st[feed].get("ok"), (feed, st[feed])
    assert "signals_errors" not in st, st.get("signals_errors")
    alerts = res["alerts"]
    text = json.dumps(alerts)
    # planted US short build-up in T007 (9% vs ~2.7%)
    assert any(a["feed"] == "US short interest" and a.get("ticker") == "T007" for a in alerts), text
    us_stock = [a for a in alerts if a["feed"] == "US short interest" and a["kind"] == "stock"]
    assert len(us_stock) == 1, us_stock  # noise stocks must not fire
    # planted HK jump in stock 5 (from 0.17% to 2% of shares)
    assert any(a["feed"] == "HK short positions" and a["ticker"] == "0005.HK" for a in alerts), text
    # UK: Shorty crossed 2% (1.6 -> 2.4)
    assert any(a["feed"] == "UK short positions" and "crossed 2%" in a["detail"] for a in alerts), text
    # sector ETF: XLE inflow surge
    assert any(a["feed"] == "Sector ETF flows" and a["ticker"] == "XLE" for a in alerts), text
    # 13F: T007 opened by every fake fund that exists
    assert any(a["feed"] == "13F (hedge funds)" and a["ticker"] == "T007" for a in alerts), text
    # Southbound movers: code 9 tops the buy list
    assert res["hk"]["sb_buys"][0]["code"] == 9
    # CFTC: leveraged funds swung to unusually long
    sp = [r for r in res["cftc"]["latest"] if r["market"] == "S&P 500 e-mini"][0]
    assert sp["flag"] == "hedge funds unusually long"
    # HSBC always reported on UK watch list
    assert res["uk"]["watch"][0]["isin"] == "GB0005405286"
    # dashboard files exist and are non-empty
    for f in ("alerts.csv", "us_sector_si.csv", "hk_top_shorts.csv", "southbound_buys.csv",
              "cftc_latest.csv", "etf_flows_latest.csv", "data_status.csv", "lookup_us.csv"):
        assert (root / "docs" / f).stat().st_size > 20, f
    # signals.json must be strict JSON (no NaN)
    json.loads((root / "docs" / "signals.json").read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))


def test_second_run_is_incremental(run_pipeline):
    res, root = run_pipeline
    from fundflow import run
    run.main()  # nothing new: should not duplicate rows
    from fundflow import store
    sfc = store.read("sfc_shorts")
    assert not sfc.duplicated(["date", "code"]).any()
