"""Stage 4: data validation and cleaning.

Each function below checks one thing and is unit-testable in isolation
(see tests/test_data_validation.py). validate_dataframe() composes them
into a single pass that returns the cleaned rows, the rejected rows (with
reasons), and a data-quality report. Rejected rows are never silently
dropped without being reported.

Distinction used throughout:
- "errors" -> row is rejected (excluded from the cleaned dataset)
- "warnings" -> row is kept, but flagged for the quality report
"""
from __future__ import annotations

import argparse
import glob
from pathlib import Path
from typing import Any

import pandas as pd

from src import storage
from src.utils import PROJECT_ROOT, get_logger, load_config

logger = get_logger(__name__)

REQUIRED_COLUMNS = ["Date", "Symbol", "Open", "High", "Low", "Close", "Volume"]


def check_required_columns(df: pd.DataFrame) -> list[str]:
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def parse_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return df


def find_null_dates(df: pd.DataFrame) -> pd.Series:
    return df["Date"].isna()


def find_null_symbols(df: pd.DataFrame) -> pd.Series:
    return df["Symbol"].isna() | (df["Symbol"].astype(str).str.strip() == "")


def find_duplicate_symbol_date(df: pd.DataFrame) -> pd.Series:
    return df.duplicated(subset=["Symbol", "Date"], keep="first")


def find_invalid_prices(df: pd.DataFrame, min_price: float, max_price: float) -> pd.Series:
    price_cols = ["Open", "High", "Low", "Close"]
    invalid = pd.Series(False, index=df.index)
    for col in price_cols:
        numeric = pd.to_numeric(df[col], errors="coerce")
        invalid = invalid | numeric.isna() | (numeric <= 0) | (numeric < min_price) | (numeric > max_price)
    return invalid


def find_negative_volume(df: pd.DataFrame) -> pd.Series:
    volume = pd.to_numeric(df["Volume"], errors="coerce")
    return volume.isna() | (volume < 0)


def find_high_lower_than_low(df: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(df["High"], errors="coerce") < pd.to_numeric(df["Low"], errors="coerce")


def find_open_close_outside_range(df: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(df["High"], errors="coerce")
    low = pd.to_numeric(df["Low"], errors="coerce")
    open_ = pd.to_numeric(df["Open"], errors="coerce")
    close = pd.to_numeric(df["Close"], errors="coerce")
    return (open_ > high) | (open_ < low) | (close > high) | (close < low)


def find_unsorted_dates(df: pd.DataFrame) -> bool:
    per_symbol_sorted = df.groupby("Symbol")["Date"].apply(lambda s: s.is_monotonic_increasing)
    return bool((~per_symbol_sorted).any())


def validate_dataframe(
    df: pd.DataFrame, symbol: str, min_price: float = 0.01, max_price: float = 1_000_000.0
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    """Returns (clean_df, rejected_df, report)."""
    report: dict[str, Any] = {"symbol": symbol, "input_rows": len(df)}

    missing_cols = check_required_columns(df)
    if missing_cols:
        report["fatal_error"] = f"Missing required columns: {missing_cols}"
        return df.iloc[0:0], df, report

    df = parse_dates(df)

    reject_mask = pd.Series(False, index=df.index)
    reasons = pd.Series([""] * len(df), index=df.index)

    checks: list[tuple[str, pd.Series]] = [
        ("null_date", find_null_dates(df)),
        ("null_symbol", find_null_symbols(df)),
        ("duplicate_symbol_date", find_duplicate_symbol_date(df)),
        ("invalid_price", find_invalid_prices(df, min_price, max_price)),
        ("negative_volume", find_negative_volume(df)),
        ("high_lower_than_low", find_high_lower_than_low(df)),
        ("open_close_outside_range", find_open_close_outside_range(df)),
    ]

    for name, mask in checks:
        mask = mask.fillna(True)
        newly_caught = mask & ~reject_mask
        reasons.loc[newly_caught] = name
        reject_mask = reject_mask | mask
        report[f"count_{name}"] = int(mask.sum())

    rejected_df = df.loc[reject_mask].copy()
    rejected_df["rejection_reason"] = reasons.loc[reject_mask]
    clean_df = df.loc[~reject_mask].copy().sort_values("Date").reset_index(drop=True)

    report["unsorted_dates_detected_in_raw_input"] = find_unsorted_dates(df.loc[~reject_mask]) if len(clean_df) else False
    report["rejected_rows"] = int(len(rejected_df))
    report["valid_rows"] = int(len(clean_df))
    report["duplicate_count"] = report["count_duplicate_symbol_date"]
    report["insufficient_data_warning"] = len(clean_df) < 30

    return clean_df, rejected_df, report


def load_latest_raw_csv(raw_dir: Path, symbol: str) -> pd.DataFrame | None:
    matches = sorted(glob.glob(str(raw_dir / f"{symbol}_*.csv")))
    if not matches:
        return None
    return pd.read_csv(matches[-1])


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate raw OHLCV data.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "settings.yaml"))
    args = parser.parse_args()

    cfg = load_config(args.config)
    data_cfg = cfg["data"]
    validation_cfg = cfg.get("validation", {})
    raw_dir = PROJECT_ROOT / data_cfg["raw_dir"]

    symbols = data_cfg["symbols"] + [data_cfg["benchmark_symbol"]]
    all_clean = []
    all_reports = []

    for symbol in symbols:
        df = load_latest_raw_csv(raw_dir, symbol)
        if df is None:
            logger.error(f"No raw CSV found for {symbol} in {raw_dir}. Run ingest_data.py first.")
            continue
        clean_df, rejected_df, report = validate_dataframe(
            df, symbol,
            min_price=validation_cfg.get("min_allowed_price", 0.01),
            max_price=validation_cfg.get("max_allowed_price", 1_000_000.0),
        )
        logger.info(f"{symbol}: {report['valid_rows']} valid / {report['input_rows']} input rows, {report['rejected_rows']} rejected")
        if report["rejected_rows"] > 0:
            logger.warning(f"{symbol} rejected rows:\n{rejected_df[['Date', 'Symbol', 'rejection_reason']].to_string(index=False)}")
        all_clean.append(clean_df)
        all_reports.append(report)

    if all_clean:
        combined = pd.concat(all_clean, ignore_index=True)
        out_dir = PROJECT_ROOT / data_cfg["processed_dir"]
        out_dir.mkdir(parents=True, exist_ok=True)
        combined.to_csv(out_dir / "validated_combined.csv", index=False)
        logger.info(f"Wrote validated combined dataset: {out_dir / 'validated_combined.csv'} ({len(combined)} rows)")

    import json
    report_path = PROJECT_ROOT / data_cfg["processed_dir"] / "data_quality_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(all_reports, f, indent=2, default=str)
    logger.info(f"Data quality report written to {report_path}")


if __name__ == "__main__":
    main()
