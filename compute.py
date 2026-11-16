#!/usr/bin/env python3
"""Recompute the frozen IPO event grid from one fetch.py output directory.

Only cohort.json and the selected download directory are inputs. This script
contains no observations and does not read ETF Equity Lab's internal/shared data.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median

import pandas_market_calendars as mcal
import exchange_calendars as xcals


PACKAGE = Path(__file__).resolve().parent
GRID = (1, 2, 5, 10, 21, 42, 63, 126, 252)
FIELDS = ("symbol_id", "d0_session", "h_sessions", "target_session", "price_status",
          "market_segment", "offer_price_usd", "d0_close_nominal_usd",
          "d0_adj_close_usd", "target_adj_close_usd", "pop_pct", "post_total_pct",
          "offer_total_pct", "market_total_pct", "post_minus_market_pp", "market_state",
          "source_csv_sha256")


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: str | int | float) -> Decimal:
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError(f"Non-finite number: {value}")
    return result


def pct(value: Decimal | None) -> str:
    return "" if value is None else format(value * 100, ".8f")


def rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def output_csv(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def load_french(path: Path) -> dict[str, tuple[Decimal, Decimal]]:
    with zipfile.ZipFile(path) as archive:
        members = archive.namelist()
        if len(members) != 1:
            raise ValueError("Expected one French CSV in ZIP")
        lines = archive.read(members[0]).decode("latin1").splitlines()
    result: dict[str, tuple[Decimal, Decimal]] = {}
    for line in lines:
        if not re.match(r"^\d{8},", line):
            if result:
                break
            continue
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5:
            raise ValueError(f"Unexpected French factor row: {line}")
        d = f"{parts[0][:4]}-{parts[0][4:6]}-{parts[0][6:]}"
        if d in result:
            raise ValueError(f"Duplicate French date: {d}")
        # Source values are percentage points, not decimal returns.
        result[d] = (number(parts[1]), number(parts[4]))
    if not result:
        raise ValueError("French ZIP has no daily observations")
    return result


def load_prices(path: Path, d0: str, cutoff: str) -> tuple[dict[str, dict[str, str]], dict[str, Decimal]]:
    data = rows(path)
    required = {"Date", "Close", "Adj Close", "Dividends", "Stock Splits"}
    if not data or not required <= data[0].keys():
        raise ValueError(f"Missing price rows/columns: {path.name}")
    dated = [r["Date"][:10] for r in data]
    if dated != sorted(set(dated)) or dated[0] < d0 or dated[-1] > cutoff:
        raise ValueError(f"Bad date range or duplicate prices: {path.name}")
    factor = Decimal(1)
    future: dict[str, Decimal] = {}
    for row in reversed(data):
        d = row["Date"][:10]
        future[d] = factor
        split = number(row["Stock Splits"])
        if split:
            if split <= 0:
                raise ValueError(f"Invalid split {path.name} {d}")
            factor *= split
    return dict(zip(dated, data, strict=True)), future


def benchmark(sessions: list[str], factors: dict[str, tuple[Decimal, Decimal]], factor_max: str) -> tuple[Decimal | None, str]:
    missing = [d for d in sessions if d not in factors]
    if missing:
        return None, "french_fuera_de_cobertura" if max(missing) > factor_max else "french_fecha_faltante"
    growth = Decimal(1)
    for d in sessions:
        mkt_rf, rf = factors[d]
        growth *= 1 + (mkt_rf + rf) / 100
    return growth - 1, "verificado"


def compute(download: Path, output: Path) -> dict:
    if output.exists():
        raise FileExistsError(f"Output directory already exists: {output}")
    if PACKAGE == output or PACKAGE in output.parents:
        raise ValueError("Output must be outside the source package")
    cohort_path = PACKAGE / "cohort.json"
    cohort = json.loads(cohort_path.read_text(encoding="utf-8"))
    manifest_path = download / "manifest.json"
    source = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases = cohort["cases"]
    if len(cases) != 16 or len({c["symbol_id"] for c in cases}) != 16:
        raise ValueError("Frozen cohort must contain 16 unique cases")
    cutoff = cohort["cutoff_session"]
    if source["package_cohort_sha256"] != sha(cohort_path):
        raise ValueError("Download was made with a different cohort.json")
    if source["end_exclusive"] != cohort["end_exclusive"]:
        raise ValueError("Download cutoff differs from cohort.json")
    records = {r["symbol_id"]: r for r in source["yahoo_records"]}
    if set(records) != {c["symbol_id"] for c in cases}:
        raise ValueError("Download manifest symbols differ from cohort")
    french_rec = source["french"]
    if french_rec["status"] != "received":
        raise ValueError("French factor download unavailable")
    french_path = download / french_rec["path"]
    if sha(french_path) != french_rec["sha256"]:
        raise ValueError("French ZIP hash mismatch")
    factors = load_french(french_path)
    factor_max = max(factors)
    cal_end = (date.fromisoformat(cutoff) + timedelta(days=430)).isoformat()
    earliest = min(c["d0_session"] for c in cases)
    calendars = {exchange: [d.strftime("%Y-%m-%d") for d in mcal.get_calendar(code).valid_days(
        start_date=earliest, end_date=cal_end)] for exchange, code in (("NYSE", "NYSE"), ("Nasdaq", "NASDAQ"))}
    results: list[dict] = []
    checks: dict[str, dict] = {}
    for case in cases:
        symbol, d0 = case["symbol_id"], case["d0_session"]
        rec = records[symbol]
        days = calendars[case["ipo_exchange"]]
        if d0 not in days:
            raise ValueError(f"D0 is not a scheduled exchange session: {symbol} {d0}")
        pos = days.index(d0)
        rowmap: dict[str, dict[str, str]] = {}
        future: dict[str, Decimal] = {}
        if rec["status"] in ("received", "received_with_warnings"):
            path = download / rec["path"]
            if sha(path) != rec["sha256"]:
                raise ValueError(f"Price CSV hash mismatch: {symbol}")
            rowmap, future = load_prices(path, d0, cutoff)
        elif rec["status"] not in ("empty", "error"):
            raise ValueError(f"Unknown price status: {symbol} {rec['status']}")
        if bool(rowmap.get(d0)) != bool(rec["d0_observed"]):
            raise ValueError(f"D0 state differs from download manifest: {symbol}")
        p0 = rowmap.get(d0)
        nominal = number(p0["Close"]) * future[d0] if p0 else None
        adj0 = number(p0["Adj Close"]) if p0 else None
        offer = number(case["offer_price_usd"])
        if offer <= 0 or (p0 and (nominal <= 0 or adj0 <= 0)):
            raise ValueError(f"Invalid D0/offer price: {symbol}")
        pop = nominal / offer - 1 if p0 else None
        checks[symbol] = {"rows": len(rowmap), "d0_observed": bool(p0), "future_split_factor_d0": str(future[d0]) if p0 else None,
                          "missing_scheduled_through_252": [], "extra_unscheduled_through_252": []}
        through = min(pos + 252, days.index(cutoff))
        planned = set(days[pos:through + 1])
        actual = {d for d in rowmap if d <= days[through]}
        checks[symbol]["missing_scheduled_through_252"] = sorted(planned - actual)
        checks[symbol]["extra_unscheduled_through_252"] = sorted(actual - planned)
        for h in GRID:
            target = days[pos + h]
            ph = rowmap.get(target)
            segment = "OTC" if symbol == "DIDI" and target >= "2022-06-13" else case["ipo_exchange"]
            if target > cutoff:
                status = "inmaduro_al_corte"
            elif not p0:
                status = "sin_historia_d0"
            elif ph is None:
                status = "sin_cotizacion_fecha_programada"
            else:
                status = "observado_otc" if segment == "OTC" else "observado"
            observed = status in ("observado", "observado_otc")
            post = from_offer = market = excess = None
            market_state = "sin_precio_accion"
            if observed:
                adjh = number(ph["Adj Close"])
                if adjh <= 0:
                    raise ValueError(f"Invalid adjusted close: {symbol} +{h}")
                post = adjh / adj0 - 1
                from_offer = (1 + pop) * (1 + post) - 1
                market, market_state = benchmark(days[pos + 1:pos + h + 1], factors, factor_max)
                if market is not None:
                    excess = post - market
            results.append({
                "symbol_id": symbol, "d0_session": d0, "h_sessions": h, "target_session": target,
                "price_status": status, "market_segment": segment, "offer_price_usd": case["offer_price_usd"],
                "d0_close_nominal_usd": format(nominal, ".10f") if p0 else "",
                "d0_adj_close_usd": p0["Adj Close"] if p0 else "",
                "target_adj_close_usd": ph["Adj Close"] if observed else "",
                "pop_pct": pct(pop), "post_total_pct": pct(post), "offer_total_pct": pct(from_offer),
                "market_total_pct": pct(market), "post_minus_market_pp": pct(excess),
                "market_state": market_state, "source_csv_sha256": rec.get("sha256", "") if p0 else "",
            })
    results.sort(key=lambda r: (r["symbol_id"], r["h_sessions"]))
    if len(results) != 16 * len(GRID):
        raise ValueError("Incomplete horizon grid")
    fixed_stock = {r["symbol_id"] for r in results if r["h_sessions"] == 126 and r["post_total_pct"]}
    fixed_pair = {r["symbol_id"] for r in results if r["h_sessions"] == 126 and r["post_minus_market_pp"]}
    coverage, medians = [], []
    for h in GRID:
        block = [r for r in results if r["h_sessions"] == h]
        counts = Counter(r["price_status"] for r in block)
        priced = [r for r in block if r["post_total_pct"]]
        paired = [r for r in priced if r["market_total_pct"]]
        stock_fixed = [r for r in block if r["symbol_id"] in fixed_stock] if h <= 126 else []
        pair_fixed = [r for r in block if r["symbol_id"] in fixed_pair] if h <= 126 else []
        coverage.append({"h_sessions": h, "eligible_n": len(cases), "observed_exchange_n": counts["observado"],
                         "observed_otc_n": counts["observado_otc"], "immature_n": counts["inmaduro_al_corte"],
                         "missing_d0_n": counts["sin_historia_d0"], "missing_target_n": counts["sin_cotizacion_fecha_programada"],
                         "stock_return_n": len(priced), "market_paired_n": len(paired),
                         "market_unavailable_n": len(priced) - len(paired),
                         "fell_from_d0_n": sum(number(r["post_total_pct"]) < 0 for r in priced),
                         "beat_market_n": sum(number(r["post_minus_market_pp"]) > 0 for r in paired),
                         "stock_fixed_126_n": len(stock_fixed), "paired_fixed_126_n": len(pair_fixed)})
        def med(group: list[dict], key: str) -> str:
            return format(median(number(r[key]) for r in group), ".8f") if group else ""
        medians.append({"h_sessions": h, "stock_all_n": len(priced), "stock_all_median_post_pct": med(priced, "post_total_pct"),
                        "stock_fixed_126_n": len(stock_fixed), "stock_fixed_126_median_post_pct": med(stock_fixed, "post_total_pct"),
                        "paired_fixed_126_n": len(pair_fixed), "paired_fixed_126_median_stock_pct": med(pair_fixed, "post_total_pct"),
                        "paired_fixed_126_median_market_pct": med(pair_fixed, "market_total_pct"),
                        "paired_fixed_126_median_excess_pp": med(pair_fixed, "post_minus_market_pp"),
                        "plus252_separate_n": len(priced) if h == 252 else "",
                        "plus252_separate_median_post_pct": med(priced, "post_total_pct") if h == 252 and len(priced) >= 6 else ""})
    indexed = {(r["symbol_id"], r["h_sessions"]): r for r in results}
    case_rows = []
    for symbol in sorted(c["symbol_id"] for c in cases):
        a, b, c = (indexed[symbol, h] for h in (63, 126, 252))
        case_rows.append({"symbol_id": symbol, "d0_session": a["d0_session"], "pop_pct": a["pop_pct"],
                          "plus63_post_pct": a["post_total_pct"], "plus63_market_pct": a["market_total_pct"],
                          "plus126_post_pct": b["post_total_pct"], "plus126_market_pct": b["market_total_pct"],
                          "plus252_post_pct": c["post_total_pct"], "plus252_market_pct": c["market_total_pct"],
                          "plus252_status": c["price_status"]})
    summary = {"eligible": len(cases), "d0_with_pop": len({r["symbol_id"] for r in results if r["pop_pct"]}),
               "plus63_stock": coverage[6]["stock_return_n"], "plus126_stock": coverage[7]["stock_return_n"],
               "editorial_gate_passes": coverage[6]["stock_return_n"] >= 8 and coverage[7]["stock_return_n"] >= 6,
               "fixed_stock_126_symbols": sorted(fixed_stock), "fixed_paired_126_symbols": sorted(fixed_pair),
               "plus252_stock_n": coverage[8]["stock_return_n"],
               "plus252_otc_symbols": sorted(r["symbol_id"] for r in results if r["h_sessions"] == 252 and r["price_status"] == "observado_otc"),
               "french_last_session": factor_max,
               "missing_benchmark_rows": sum(r["market_state"] == "french_fuera_de_cobertura" for r in results)}
    output.mkdir(parents=True)
    output_csv(output / "case_horizon.csv", results)
    output_csv(output / "coverage.csv", coverage)
    output_csv(output / "medians.csv", medians)
    output_csv(output / "case_summary.csv", case_rows)
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "qa.json").write_text(json.dumps({"cases": checks, "source_status": {s: r["status"] for s, r in records.items()}},
                                                 indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    manifest = {"run_id": "mega_ipos_ant_ed5_public_reproduction", "created_utc": datetime.now(timezone.utc).isoformat(),
                "cutoff_session": cutoff, "parameters": {"grid_sessions": GRID,
                "benchmark": "French Mkt-RF+RF, D0 exclusive to target inclusive; factor values in percent",
                "return_basis": "Yahoo Adj Close; offer pop from nominal D0 Close reconstructed using future split factors"},
                "versions": {"python": sys.version.split()[0], "pandas_market_calendars": mcal.__version__,
                             "exchange_calendars": xcals.__version__, "fetch_python": source.get("python_version"),
                             "fetch_yfinance": source.get("yfinance_version"), "fetch_pandas": source.get("pandas_version")},
                "input_hashes": {"cohort.json": sha(cohort_path), "download_manifest.json": sha(manifest_path),
                                 "french_zip": sha(french_path),
                                 **{f"{s}.csv": r["sha256"] for s, r in records.items() if "sha256" in r}},
                "code_sha256": sha(Path(__file__)),
                "output_hashes": {p.name: sha(p) for p in output.iterdir() if p.is_file()}, "summary": summary}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Directory created by fetch.py")
    parser.add_argument("--output", type=Path, required=True, help="New, separate output directory")
    args = parser.parse_args()
    print(json.dumps(compute(args.input.resolve(), args.output.resolve()), ensure_ascii=False))


if __name__ == "__main__":
    main()
