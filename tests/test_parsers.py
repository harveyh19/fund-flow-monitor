import io
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from fundflow.collectors import cftc, fca, finra, sec13f, sfc, southbound, spdr
from fundflow.util import finra_candidates, fridays_back, norm_ticker, pct_rank, zscore

FX = Path(__file__).parent / "fixtures"


def test_sfc_real_file():
    df = sfc.parse((FX / "sfc_20261023.csv").read_text())
    assert len(df) > 1200
    hsbc = df[df["code"] == 5].iloc[0]
    assert hsbc["date"] == "2026-10-23"
    assert hsbc["short_shares"] == 69280647
    assert hsbc["short_hkd"] == 9872492198


def test_finra_real_file_filters_otc():
    df = finra.parse((FX / "finra_sample.csv").read_text())
    assert set(df["market"]) <= {"NNM", "NYSE", "ARCA", "SC", "BZX", "AMEX", "TXSE"}
    a = df[df["symbol"] == "A"].iloc[0]
    assert a["short_shares"] == 5025670 and a["days_to_cover"] == 2.42
    assert a["settlement_date"] == "2026-10-15"


def test_southbound_real_page():
    df = southbound.parse((FX / "southbound_sample.html").read_text())
    assert df["date"].iloc[0] == "2026-11-06"
    ck = df[df["code"] == 1].iloc[0]
    assert ck["sb_shares"] == 64605571 and ck["sb_pct"] == 1.68
    # implied issued shares = 64,605,571 / 1.68%
    assert ck["issued_shares"] == pytest.approx(64605571 / 0.0168)
    assert len(df) == 27  # rows in the trimmed fixture (counted independently by regex)


def test_fca_flexible_columns():
    text = ("Name of company,ISIN,Aggregate net short position (%),Position date\n"
            "HSBC Holdings plc,GB0005405286,0.35,05/11/2026\n"
            "Ocado Group,GB00B3MBS747,6.10,05/11/2026\n")
    df = fca.parse(text, "current")
    assert list(df["pct"]) == [0.35, 6.10]
    assert df["position_date"].iloc[0] == "2026-11-05"


def test_spdr_layout():
    rows = [["Fund Name:", "SPDR"], ["Ticker Symbol:", "XLK"], [None, None],
            ["Date", "NAV", "Shares Outstanding", "Total Net Assets"],
            ["05-Nov-2026", 162.2975, 663761794.0, 1.0],
            ["04-Nov-2026", 176.428254, 662811794.0, 1.0],
            ["03-Nov-2026", 176.542181, 663061794.0, 1.0]]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    df = spdr.parse(buf.getvalue(), "XLK")
    assert list(df["date"]) == ["2026-11-04", "2026-11-05"]
    # 4 Nov: shares fell 250,000 x NAV 176.428254
    assert df.iloc[0]["flow_usd"] == pytest.approx(-250000 * 176.428254)
    assert df.iloc[1]["flow_usd"] == pytest.approx(950000 * 162.2975)


def test_cftc_shape_picks_biggest_market():
    base = {"report_date_as_yyyy_mm_dd": "2026-11-03T00:00:00.000",
            "asset_mgr_positions_long": "10", "asset_mgr_positions_short": "5",
            "lev_money_positions_long": "3", "lev_money_positions_short": "9",
            "dealer_positions_long_all": "1", "dealer_positions_short_all": "1"}
    rows = [dict(base, market_and_exchange_names="E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE",
                 open_interest_all="100"),
            dict(base, market_and_exchange_names="E-MINI S&P 500 - OTHER EXCHANGE",
                 open_interest_all="5"),
            dict(base, market_and_exchange_names="WHEAT - CBOT", open_interest_all="999")]
    df = cftc.shape(rows)
    assert list(df["market"]) == ["E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE"]
    assert df["label"].iloc[0] == "S&P 500 e-mini" and df["lev_short"].iloc[0] == 9


def test_13f_infotable_namespaces_and_aggregation():
    xml = b"""<?xml version="1.0"?>
    <informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
     <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
      <cusip>037833100</cusip><value>1000</value>
      <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
     <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>COM</titleOfClass>
      <cusip>037833100</cusip><value>500</value>
      <shrsOrPrnAmt><sshPrnamt>5</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
     <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><titleOfClass>CALL</titleOfClass>
      <cusip>037833100</cusip><value>70</value><putCall>Call</putCall>
      <shrsOrPrnAmt><sshPrnamt>1</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
    </informationTable>"""
    df = sec13f.parse_infotable(xml)
    stock = df[df["putCall"] == ""].iloc[0]
    assert stock["value_usd"] == 1500 and stock["shares"] == 15
    assert (df["putCall"] == "CALL").sum() == 1
    old = sec13f.parse_infotable(xml, value_in_thousands=True)
    assert old[old["putCall"] == ""]["value_usd"].iloc[0] == 1500000


def test_helpers():
    assert norm_ticker("BRK.B") == norm_ticker("BRK-B") == "BRKB"
    assert pct_rank([1, 2, 3, 4], 5) == 100
    assert pct_rank([1, 2, 3, 4], 0) == 0
    assert abs(zscore([1, 2, 3, 4, 5], 5) - 1.2649) < 1e-3
    mid, late = finra_candidates(2026, 11)
    assert mid[0] == date(2026, 11, 13)  # the 15th is a Sunday -> 13th first weekday tried
    assert late[0] == date(2026, 11, 30)
    assert fridays_back(2, date(2026, 11, 7)) == [date(2026, 11, 6), date(2026, 10, 30)]
