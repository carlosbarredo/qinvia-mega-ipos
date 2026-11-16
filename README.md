# Mega IPOs: public price reproduction

**Languages:** [English](README.md) · [Español](README_ES.md)

This package reconstructs the **price and return tables** for the study's cohort of 16 IPOs using freely accessible data, working edition 5 (2026-11-16). It contains code and cohort metadata only: no market prices, downloaded factors, or derived results. It runs outside ETF Equity Lab's infrastructure and requires no internal `shared` directory or study paths.

## Install and run

Tested with **Python 3.15.2** and the versions pinned in `requirements.txt`. From this directory, in an existing Python 3.15 environment:

```bash
python3.15 -m pip install -r requirements.txt
python3.15 fetch.py --out /tmp/mega_ipos_download_20261116
python3.15 compute.py \
  --input /tmp/mega_ipos_download_20261116 \
  --output /tmp/mega_ipos_calculation_20261116
```

Replace both `/tmp/` paths with your own local directories **outside this repository** if you want to keep the outputs. Each output path must be new: the scripts refuse existing directories to avoid overwriting a prior run. Fetching requires access to Yahoo Finance and [Kenneth French's Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). `fetch.py` requests each of the 16 cases once and downloads a factor ZIP. Its manifest reports `received`, `empty`, or `error` for each case. If it exits with code 2, inspect that manifest before calculating.

## Outputs

| Directory | File | Contents |
|---|---|---|
| Download | `raw/yahoo/<symbol>.csv` | Daily bars returned by `yfinance.Ticker.history`, one file per symbol with observations. |
| Download | `raw/french/f_f_research_data_factors_daily_csv.zip` | Original French daily factor file. |
| Download | `manifest.json` | UTC time, versions, parameters, status, row counts, and SHA-256 of each saved response. |
| Calculation | `case_horizon.csv` | 16 cases × 9 horizons = 144 positions, with target session, status, first-day pop, and returns when available. |
| Calculation | `case_summary.csv`, `coverage.csv`, `medians.csv` | IPO summaries, coverage by horizon, and medians with sample sizes. |
| Calculation | `summary.json`, `qa.json`, `manifest.json` | Counts, gaps, calendar checks, versions, and input/output SHA-256 hashes. |

Dates, offer prices, tickers, and SEC prospectus links for the 16 cases are in `cohort.json`. D0 is the first trading session fixed by the study. The prospectus supports the offer information, while `d0_date_basis` records the basis for the date. The program checks whether the downloaded bars include D0; it does not independently reverify every IPO fact.

## Calculation definitions

Downloads start at D0 and end with the **2026-11-13** session, inclusive; the request uses the exclusive `end=2026-11-14`. `fetch.py` calls [`Ticker.history`](https://ranaroussi.github.io/yfinance/reference/yfinance.price_history.html) with `interval="1d"`, `auto_adjust=False`, `actions=True`, `repair=False`, `keepna=True`, and `prepost=False`. This retains `Close`, `Adj Close`, dividends, and splits for reviewing adjustments. The CSV files are *yfinance* output, not copies of Yahoo's original HTTP responses.

`compute.py` schedules sessions +1, +2, +5, +10, +21, +42, +63, +126, and +252 using NYSE or Nasdaq calendars from [`pandas_market_calendars`](https://pandas-market-calendars.readthedocs.io/). The **first-day pop** compares the offer price with the **nominal** D0 close. If later splits occurred, it reconstructs that nominal close from `Close` and the split factors. This matters for Visa's 4:1 split in 2015. The subsequent return compares `Adj Close` at the target session with `Adj Close` at D0. The return from offer chains the pop and the subsequent return. Columns ending in `*_pct` are percentages with eight decimal places; `post_minus_market_pp` is a difference in percentage points.

The market comparator compounds `Mkt-RF + RF` from the [daily Fama/French Research Data Factors](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library/f-f_factors.html), from the session after D0 through the target session. Source factor values are in percent, so the code divides them by 100 before compounding. `post_minus_market_pp` subtracts the compounded market return from the stock's subsequent return. The fixed-sample median curve through +126 includes only cases with a return at +126; the market-paired curve uses the subset with both returns. +252 is reported separately with its actual sample size.

## Limits of interpretation and reproduction

- **Coverage:** in the 2026-11-16 test, 15 of 16 cases had a valid D0, with returns for 15 at +63, 14 at +126, and 12 at +252. KVUE did not return D0; its returns remain blank. Target dates after the cutoff receive `inmaduro_al_corte`, never a zero return.
- **Exchange continuity:** DIDI is downloaded under its current ticker `DIDIY`, supported by its [SEC Form 20-F](https://www.sec.gov/Archives/edgar/data/1764757/000110465923053304/didi-20221231x20f.htm). Its segment from 2022-06-13 is labeled OTC, including +252; it is not presented as continuous NYSE trading.
- **Benchmark:** in the test, the French file ended on **2026-09-30**. When a stock price exists beyond the factor coverage, its market and excess returns remain blank. A later run may receive an extended factor file.
- **Provider changes:** a new download can differ from edition 5 even with identical code and cutoff. In the 2026-11-16 local check, `Adj Close` values changed for **BABA, GM, META, and V**; their `Close`, dates, dividends, and splits matched. Derived returns changed slightly, with no changes in coverage or target dates. The package records hashes and versions for each run; it does not claim to know the provider's internal cause.
- **Scope:** the scripts reproduce the tables used for price and return figures. They do not generate the figures or reconstruct the Wikipedia and Google Trends series. The automatic comparison with frozen edition 5 files was performed inside the study; those files are not part of this public package. To compare published figures, use the public web article when available and the files from your own run.

Missing observations retain their status in `case_horizon.csv` and `coverage.csv`; none is filled with a zero return.

## Sources and terms of use

Prices come from [Yahoo Finance through yfinance](https://ranaroussi.github.io/yfinance/), which documents the download interface. Factors come from [Kenneth French's Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html). Offer prices have a link to the final [SEC](https://www.sec.gov/edgar/search/) prospectus for each case in `cohort.json`. Check each provider's terms before redistributing its data: this package distributes the procedure and source references, not the downloaded series.

## License

The original code in `fetch.py` and `compute.py` is available under the [MIT License](LICENSE). That license grants no rights to Yahoo Finance prices, Kenneth French factors, or SEC documents. Downloaded files stay on the reader's machine and remain subject to their sources' terms. `cohort.json` contains provenance metadata and links, not market time series.
