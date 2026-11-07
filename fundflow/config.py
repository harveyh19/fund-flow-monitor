"""Static configuration: which funds, ETFs and futures markets to follow.

Every SEC CIK below is checked against the filer name SEC returns
(the `expect` keyword). A CIK whose SEC name does not contain the keyword is
skipped and reported in data_status, so a wrong number cannot silently pull
the wrong fund's holdings.
"""

# --- 13F filers -----------------------------------------------------------
# (cik, expect keyword in SEC filer name (case-insensitive), display label)
# Concentrated stock-pickers: used for "consensus" new positions / exits.
HEDGE_FUNDS = [
    (1067983, "berkshire", "Berkshire Hathaway"),
    (1336528, "pershing", "Pershing Square"),
    (1656456, "appaloosa", "Appaloosa"),
    (1040273, "third point", "Third Point"),
    (1061768, "baupost", "Baupost"),
    (1103804, "viking", "Viking Global"),
    (1061165, "lone pine", "Lone Pine"),
    (1135730, "coatue", "Coatue"),
    (1167483, "tiger global", "Tiger Global"),
    (1536411, "duquesne", "Duquesne Family Office"),
    (1029160, "soros", "Soros Fund Mgmt"),
    (1709323, "himalaya", "Himalaya Capital (Li Lu)"),
    (1762304, "hhlr", "Hillhouse (HHLR)"),
    (1791786, "elliott", "Elliott"),
]

# Multi-strategy, quant and macro funds: thousands of positions each, so
# they feed sector shifts and net flows, not the consensus counts.
MULTISTRAT_FUNDS = [
    (1350694, "bridgewater", "Bridgewater"),
    (1037389, "renaissance", "Renaissance Technologies"),
    (1423053, "citadel", "Citadel Advisors"),
    (1273087, "millennium", "Millennium"),
    (1179392, "two sigma", "Two Sigma"),
    (1009207, "shaw", "D. E. Shaw"),
    (1603466, "point72", "Point72"),
    (1167557, "aqr", "AQR"),
]

LARGE_MANAGERS = [
    (102909, "vanguard", "Vanguard"),
    (1364742, "blackrock", "BlackRock"),
    (93751, "state street", "State Street"),
    (315066, "fmr", "Fidelity (FMR)"),
    (1422848, "capital research", "Capital Research Global"),
    (1422849, "capital world", "Capital World Investors"),
    (19617, "jpmorgan", "JPMorgan Chase"),
    (886982, "goldman", "Goldman Sachs"),
    (895421, "morgan stanley", "Morgan Stanley"),
    (80255, "price", "T. Rowe Price"),
    (902219, "wellington", "Wellington"),
    (1374170, "norges", "Norges Bank"),
    (1214717, "geode", "Geode Capital"),
]

# --- Sector ETF flows (State Street SPDR, daily NAV + shares outstanding) --
SPDR_ETFS = {
    "SPY": "S&P 500 (whole market)",
    "XLK": "Information Technology",
    "XLF": "Financials",
    "XLV": "Health Care",
    "XLE": "Energy",
    "XLI": "Industrials",
    "XLY": "Consumer Discretionary",
    "XLP": "Consumer Staples",
    "XLU": "Utilities",
    "XLB": "Materials",
    "XLRE": "Real Estate",
    "XLC": "Communication Services",
}
SPDR_URL = ("https://www.ssga.com/us/en/intermediary/library-content/products/"
            "fund-data/etfs/us/navhist-us-en-{t}.xlsx")

# --- CFTC Traders in Financial Futures (futures only) ---------------------
# (regex on market_and_exchange_names, label). If a pattern matches several
# markets the one with the largest open interest is used.
CFTC_MARKETS = [
    (r"^E-MINI S&P 500 -", "S&P 500 e-mini"),
    (r"^NASDAQ MINI -", "Nasdaq-100 mini"),
    (r"^RUSSELL E-MINI -", "Russell 2000 e-mini"),
    (r"^MSCI EM INDEX", "MSCI Emerging Markets"),
    (r"^MSCI EAFE", "MSCI EAFE (developed ex-US)"),
    (r"^NIKKEI STOCK AVERAGE YEN", "Nikkei 225 (yen)"),
    (r"^VIX FUTURES", "VIX"),
    (r"^UST 10Y NOTE", "US 10-year Treasury"),
]
CFTC_URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"

# --- Other sources ----------------------------------------------------------
FINRA_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{d}.csv"
FINRA_EXCHANGE_CLASSES = {"NNM", "NYSE", "ARCA", "SC", "BZX", "AMEX", "TXSE"}
SFC_URL = ("https://www.sfc.hk/-/media/EN/pdf/spr/{y}/{m:02d}/{d:02d}/"
           "Short_Position_Reporting_Aggregated_Data_{y}{m:02d}{d:02d}.csv")
SOUTHBOUND_URL = "https://www3.hkexnews.hk/sdw/search/mutualmarket.aspx?t=hk"
FCA_CURRENT_URL = ("https://www.fca.org.uk/publication/documents/"
                   "aggregated-current-net-short-positions.csv")
FCA_HISTORIC_URL = ("https://www.fca.org.uk/publication/documents/"
                    "aggregated-historic-net-short-positions.csv")
SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FRAMES_URL = ("https://data.sec.gov/api/xbrl/frames/dei/"
                  "EntityCommonStockSharesOutstanding/shares/{period}.json")
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/"
OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
WIKI_SP_PAGES = {
    "S&P 500": "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
    "S&P 400": "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies",
    "S&P 600": "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies",
}

# Watch list that is always reported on, whatever the alert rules say.
# Harvey's own holdings are added at digest time from his Google Sheet.
UK_ALWAYS = {"GB0005405286": "HSBC Holdings"}

# --- Alert thresholds -------------------------------------------------------
TH = {
    "hk_short_pctile": 95,          # short % of shares at top 5% of own 52 weeks
    "hk_short_jump_pp": 1.0,        # or up >= 1 percentage point in a week
    "hk_short_min_hkd": 50e6,       # ignore short positions under HK$50m
    "us_si_pctile": 95,             # short interest at top 5% of own 1-year history
    "us_si_min_pct": 3.0,           # ... and at least 3% of shares outstanding
    "us_si_min_rise": 0.25,         # ... and up >= 25% versus 3 settlements earlier
    "us_market_pctile": 98,         # aggregate short interest near 3-year high
    "sector_si_pctile": 95,
    "sb_top_n": 20,                 # Southbound biggest 5-day changes
    "sb_z": 2.0,                    # Southbound unusual move (z-score vs own history)
    "uk_levels": (1.0, 2.0, 3.0),   # UK aggregate short crosses these %
    "uk_jump_pp": 0.5,
    "f13_consensus_n": 3,           # >= 3 of the stock-picking hedge funds open / exit
    "f13_min_weight": 0.25,         # ... counting only positions >= 0.25% of the fund
    "f13_map_top_n": 300,           # CUSIPs mapped to tickers: all for stock-pickers,
                                    # top 300 by value for the big multi-position filers
    "etf_pctile_hi": 95,
    "etf_pctile_lo": 5,
    "cftc_pctile_hi": 90,
    "cftc_pctile_lo": 10,
}
