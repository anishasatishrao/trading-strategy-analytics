"""Stage 6: monthly performance and annualized-return KPIs.

Most KPIs are computed directly inside backtest.compute_summary(), which
has direct access to the trade list. This module holds the two KPIs that
need the dated daily history: monthly returns, and the annualized return
(gated by evaluation length so it isn't reported as reliable when the
backtest only covers a few months of data).
"""
from __future__ import annotations

import argparse
import json

import pandas as pd

from src.utils import PROJECT_ROOT, get_logger, load_config

logger = get_logger(__name__)

MIN_DAYS_FOR_ANNUALIZATION = 365


def calculate_monthly_returns(history_df: pd.DataFrame) -> pd.DataFrame:
    df = history_df.copy()
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")
    monthly_portfolio = df["portfolio_value"].resample("ME").last()
    monthly_benchmark = df["benchmark_value"].resample("ME").last()

    monthly = pd.DataFrame(
        {
            "portfolio_value_month_end": monthly_portfolio,
            "benchmark_value_month_end": monthly_benchmark,
        }
    )
    monthly["strategy_monthly_return_pct"] = monthly["portfolio_value_month_end"].pct_change() * 100
    monthly["benchmark_monthly_return_pct"] = monthly["benchmark_value_month_end"].pct_change() * 100
    monthly = monthly.reset_index().rename(columns={"Date": "month"})
    return monthly


def calculate_annualized_return(total_return_pct: float, num_calendar_days: int) -> dict:
    if num_calendar_days < MIN_DAYS_FOR_ANNUALIZATION:
        return {
            "annualized_return_pct": None,
            "reliable": False,
            "reason": (
                f"Evaluation period is only {num_calendar_days} calendar days "
                f"(< {MIN_DAYS_FOR_ANNUALIZATION}); annualizing a sub-year return "
                "extrapolates noise and is not reported."
            ),
        }
    years = num_calendar_days / 365.25
    total_return_multiple = 1 + (total_return_pct / 100)
    if total_return_multiple <= 0:
        return {
            "annualized_return_pct": None,
            "reliable": False,
            "reason": "Portfolio value went to zero or negative; CAGR is undefined.",
        }
    annualized = (total_return_multiple ** (1 / years) - 1) * 100
    return {"annualized_return_pct": annualized, "reliable": True, "reason": None}


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute monthly and annualized KPIs.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "settings.yaml"))
    parser.add_argument("--symbol", default=None)
    args = parser.parse_args()

    cfg = load_config(args.config)
    symbol = args.symbol or cfg["strategy"]["default_symbol"]
    processed_dir = PROJECT_ROOT / cfg["data"]["processed_dir"]

    history_path = processed_dir / f"portfolio_history_{symbol}.parquet"
    summary_path = processed_dir / f"summary_{symbol}.json"
    if not history_path.exists() or not summary_path.exists():
        logger.error(f"Missing backtest outputs for {symbol}. Run backtest.py first.")
        raise SystemExit(1)

    history_df = pd.read_parquet(history_path)
    with open(summary_path) as f:
        summary = json.load(f)

    monthly = calculate_monthly_returns(history_df)
    monthly.to_parquet(processed_dir / f"monthly_returns_{symbol}.parquet", index=False)

    num_days = (pd.to_datetime(history_df["Date"]).max() - pd.to_datetime(history_df["Date"]).min()).days
    annualized = calculate_annualized_return(summary["total_return_pct"], num_days)
    summary.update(annualized)

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Monthly returns + annualized KPI written for {symbol}. Annualized reliable={annualized['reliable']}")


if __name__ == "__main__":
    main()
