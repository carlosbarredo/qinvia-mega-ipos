#!/usr/bin/env python3
"""Download the frozen IPO cohort and French factors into an explicit local directory.

This package contains no downloaded observations. The output directory is separate
from the source tree. A run is immutable: existing output directories are refused.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import re
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf


PACKAGE = Path(__file__).resolve().parent
COHORT = PACKAGE / "cohort.json"
FRENCH_URL = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_daily_CSV.zip"
FRENCH_LIBRARY = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html"
HISTORY_ARGS = {
    "interval": "1d",
    "auto_adjust": False,
    "actions": True,
    "repair": False,
    "keepna": True,
    "prepost": False,
}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_new(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())


def download_yahoo(case: dict, end_exclusive: str, out: Path) -> dict:
    symbol = case["symbol_id"]
    ticker = case["download_ticker"]
    start = case["d0_session"]
    record = {
        "symbol_id": symbol,
        "requested_ticker": ticker,
        "start_inclusive": start,
        "end_exclusive": end_exclusive,
        "history_args": HISTORY_ARGS,
        "received_utc": now(),
    }
    try:
        frame = yf.Ticker(ticker).history(
            start=start,
            end=end_exclusive,
            **HISTORY_ARGS,
        )
        record["received_utc"] = now()
        record["rows"] = int(len(frame))
        if frame.empty:
            record["status"] = "empty"
            record["d0_observed"] = False
            return record
        dates = [index.date() for index in frame.index]
        record["first_session"] = dates[0].isoformat()
        record["last_session"] = dates[-1].isoformat()
        record["timezone"] = str(frame.index.tz)
        record["columns"] = list(frame.columns)
        record["d0_observed"] = date.fromisoformat(start) in dates
        record["duplicate_dates"] = len(set(dates)) != len(dates)
        record["sorted_dates"] = dates == sorted(dates)
        record["out_of_request_dates"] = [d.isoformat() for d in dates if d < date.fromisoformat(start) or d >= date.fromisoformat(end_exclusive)]
        for column in ("Close", "Adj Close", "Dividends", "Stock Splits"):
            record[f"{column.lower().replace(' ', '_')}_nulls"] = int(frame[column].isna().sum()) if column in frame else None
        record["split_event_rows"] = int((frame["Stock Splits"].fillna(0) != 0).sum()) if "Stock Splits" in frame else None
        record["dividend_event_rows"] = int((frame["Dividends"].fillna(0) != 0).sum()) if "Dividends" in frame else None
        if symbol == "V" and "Stock Splits" in frame:
            record["visa_2015_03_19_split_factor"] = (
                float(frame.loc[frame.index.date == date(2015, 3, 19), "Stock Splits"].iloc[0])
                if date(2015, 3, 19) in dates else None
            )
        csv_bytes = frame.to_csv(index_label="Date", float_format="%.12g").encode("utf-8")
        rel = f"raw/yahoo/{symbol}.csv"
        write_new(out / rel, csv_bytes)
        record.update({"path": rel, "sha256": digest(csv_bytes), "bytes": len(csv_bytes)})
        essential = {"Open", "High", "Low", "Close", "Adj Close", "Volume", "Dividends", "Stock Splits"}
        record["missing_columns"] = sorted(essential - set(frame.columns))
        record["status"] = "received" if not (
            record["duplicate_dates"] or not record["sorted_dates"] or record["out_of_request_dates"] or record["missing_columns"]
        ) else "received_with_warnings"
        return record
    except Exception as exc:
        record["status"] = "error"
        record["error_type"] = type(exc).__name__
        record["error_message"] = str(exc)[:500]
        return record


def french_metadata(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        if len(names) != 1 or not names[0].lower().endswith(".csv"):
            raise ValueError(f"Unexpected French ZIP members: {names}")
        text = archive.read(names[0]).decode("latin-1")
        daily_dates = [m.group(1) for line in text.splitlines() if (m := re.match(r"^\s*(\d{8})\s*,", line))]
        if not daily_dates:
            raise ValueError("No 8-digit daily date rows in French CSV")
        return {
            "zip_member": names[0],
            "daily_rows": len(daily_dates),
            "first_daily_date": datetime.strptime(daily_dates[0], "%Y%m%d").date().isoformat(),
            "last_daily_date": datetime.strptime(daily_dates[-1], "%Y%m%d").date().isoformat(),
            "unit_note": "French source factors are daily percentage points; do not interpret as decimal returns.",
        }


def download_french(out: Path) -> dict:
    record = {"url": FRENCH_URL, "library_page": FRENCH_LIBRARY, "requested_utc": now()}
    try:
        response = requests.get(FRENCH_URL, timeout=60, headers={"User-Agent": "etf-equity-lab-public-reproduction/1.0"})
        record["received_utc"] = now()
        record["http_status"] = response.status_code
        response.raise_for_status()
        data = response.content
        record.update(french_metadata(data))
        rel = "raw/french/f_f_research_data_factors_daily_csv.zip"
        write_new(out / rel, data)
        record.update({"status": "received", "path": rel, "sha256": digest(data), "bytes": len(data)})
    except Exception as exc:
        record.update({"status": "error", "error_type": type(exc).__name__, "error_message": str(exc)[:500]})
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path, help="New local output directory, outside the package")
    args = parser.parse_args()
    out = args.out.expanduser().resolve()
    if out == PACKAGE or PACKAGE in out.parents:
        parser.error("--out must be outside the source package")
    if out.exists():
        parser.error("--out must be a new directory; existing paths are not overwritten")
    cohort_bytes = COHORT.read_bytes()
    cohort = json.loads(cohort_bytes)
    cases = cohort["cases"]
    assert len(cases) == 16 and len({c["symbol_id"] for c in cases}) == 16
    assert cohort["end_exclusive"] == "2026-11-14"
    for case in cases:
        assert date.fromisoformat(case["d0_session"]) < date.fromisoformat(cohort["end_exclusive"])
        assert case["offer_price_usd"] > 0
    out.mkdir(parents=True)
    records = []
    for case in cases:
        record = download_yahoo(case, cohort["end_exclusive"], out)
        records.append(record)
        print(case["symbol_id"], record["status"], record.get("rows", 0), flush=True)
    french = download_french(out)
    print("French", french["status"], french.get("last_daily_date", ""), flush=True)
    manifest = {
        "schema_version": 1,
        "run_utc": now(),
        "package_cohort_sha256": digest(cohort_bytes),
        "package_fetch_sha256": digest(Path(__file__).read_bytes()),
        "python_version": platform.python_version(),
        "yfinance_version": yf.__version__,
        "pandas_version": pd.__version__,
        "requests_version": requests.__version__,
        "out_dir": str(out),
        "end_exclusive": cohort["end_exclusive"],
        "history_args": HISTORY_ARGS,
        "yahoo_records": records,
        "french": french,
        "note": "CSV is yfinance Ticker.history output, not raw Yahoo HTTP. No missing price is imputed. Later provider revisions can change results.",
    }
    write_new(out / "manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    print("manifest", out / "manifest.json", flush=True)
    return 0 if french["status"] == "received" and all(r["status"] in {"received", "received_with_warnings", "empty"} for r in records) else 2


if __name__ == "__main__":
    sys.exit(main())
