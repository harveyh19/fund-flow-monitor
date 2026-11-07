# Fund Flow Monitor

Weekly, free-data view of where professional money is moving: short
positions, mainland China (Southbound) flows into Hong Kong, hedge-fund and
large-manager 13F holdings, futures positioning and sector ETF flows.

This repository holds **market data only**. Personal holdings stay in a
private Google Sheet and are joined in only by the private dashboard and the
weekly digest.

## What runs, and when

`.github/workflows/weekly.yml` runs every **Saturday 08:30 Hong Kong time**
(and on demand from the Actions tab). It:

1. runs the offline self-tests (`pytest`),
2. downloads every feed (`python -m fundflow.run`),
3. commits history to `data/` and this week's results to `docs/`.

The first run backfills about 3 years and takes 30–60 minutes (most of it is
mapping 13F CUSIPs to tickers on OpenFIGI's free tier). Later runs take a few
minutes.

## Feeds

| Feed | Source | Frequency / lag | Evidence that it predicts returns |
|---|---|---|---|
| US short interest | FINRA bi-monthly files | twice a month, ~1 week lag | strong |
| HK short positions | SFC aggregated reportable short positions | weekly, ~1 week lag | strong (short interest) |
| UK short positions | FCA aggregate net short positions (≥0.2% notifications) | daily, T+2 | strong (short interest) |
| Southbound holdings | HKEX Stock Connect shareholding search | daily, T+1 | good (Ding et al., 2025) |
| 13F holdings | SEC EDGAR, 37 tracked managers | quarterly, up to 45 days lag | context only |
| Futures positioning | CFTC Traders in Financial Futures | weekly, Tuesday data | context only |
| Sector ETF flows | State Street SPDR NAV + shares outstanding | daily | context only |

Not yet covered: country ETF flows (iShares blocks automated downloads),
Hong Kong sector aggregation (no free sector classification).

## Outputs (`docs/`)

* `signals.json` – everything, used by the weekly digest
* `alerts.csv` – this week's alerts, each tagged `strong` / `good` / `context`
* one CSV per dashboard table (`us_sector_si.csv`, `southbound_buys.csv`, …)
* `lookup_*.csv` – per-stock numbers used to match personal holdings
* `data_status.csv` – whether each feed worked and how fresh it is

## Alert rules (`fundflow/config.py`, `TH`)

* **HK shorts**: short % of shares at a 52-week high (top 5%) or up ≥1
  percentage point in a week; positions under HK$50m ignored.
* **US shorts** (S&P 1500): short % at a 1-year high (top 5%) **and** ≥3% of
  shares **and** up ≥25% versus ~6 weeks earlier. Sector totals at a 3-year
  high (top 5%). Market-wide average near a 3-year high (top 2%).
* **UK shorts**: aggregate short crosses 1%, 2% or 3%, or rises ≥0.5 pp in a
  week. HSBC is always shown.
* **Southbound**: 20 biggest one-week buys and sells; an alert when a stock's
  move is ≥2 standard deviations of its own weekly history and ≥HK$50m.
* **13F**: ≥3 of the stock-picking hedge funds open (or exit) the same stock,
  counting only positions ≥0.25% of a fund.
* **ETF flows**: 4-week flow as % of fund size in the top or bottom 5% of
  3 years.
* **Futures**: leveraged funds' net position in the top or bottom 10% of
  3 years (context).

Percentiles compare this week with each series' own past, so thresholds adapt
to each stock.

## Known approximations

* US short % uses the latest SEC cover-page share count for the whole
  history; companies with several share classes are flagged `multi_class`.
* HK short % uses issued shares implied by HKEX's Southbound table, so it is
  only available for Southbound-eligible stocks.
* Southbound flow in HK$ is shares bought × the latest SFC price; it covers
  stocks on the SFC short-reporting list.
* The S&P 1500 list is today's constituents (survivorship bias in the
  market-wide average).
* 13F shows long US-listed positions at quarter end only — never shorts.

## Repository secrets (Settings → Secrets and variables → Actions)

* `SEC_USER_AGENT` (recommended): SEC asks automated clients to identify
  themselves, e.g. `Firstname Lastname contact@example.com`.
* `OPENFIGI_API_KEY` (optional, free from openfigi.com): makes CUSIP mapping
  about 10× faster.

## Local use

```bash
pip install -r requirements.txt
python -m pytest -q          # offline tests, no network
python -m fundflow.run       # full collection (needs internet)
python -m fundflow.run --only signals   # recompute from stored data
```
