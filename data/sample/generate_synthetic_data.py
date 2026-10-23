"""Generates SYNTHETIC demonstration OHLCV data.

IMPORTANT: this is NOT real market data. It exists only so the pipeline
can be demonstrated end-to-end when live data access (yfinance) is
unreachable -- which is exactly the situation in the sandbox this project
was built in (Yahoo Finance rate-limited the sandbox's outbound IP; see
README "Known Limitations"). Every file this script writes is named
<SYMBOL>_SYNTHETIC_<start>_<end>.csv and carries a Data_Source column set
to "SYNTHETIC_DEMO", so it can never be mistaken for genuine NSE data
downstream (validate_data.py and the dashboard both surface this column).

Run on a machine with normal internet access: use ingest_data.py instead,
which pulls real data via yfinance.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

RNG = np.random.default_rng(seed=42)  # fixed seed: reproducible synthetic data

SAMPLE_DIR = Path(__file__).resolve().parent


def generate_one_symbol(
    symbol: str, start: str, end: str, start_price: float, annual_drift: float, annual_vol: float
) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, end=end)
    n = len(dates)
    daily_drift = annual_drift / 252
    daily_vol = annual_vol / np.sqrt(252)

    # Geometric random walk with a few injected multi-week uptrends so the
    # breakout strategy actually has signals to trade on in the demo.
    shocks = RNG.normal(daily_drift, daily_vol, n)
    num_trends = max(2, n // 180)
    for _ in range(num_trends):
        trend_start = RNG.integers(0, max(1, n - 40))
        trend_len = RNG.integers(15, 35)
        trend_end = min(n, trend_start + trend_len)
        shocks[trend_start:trend_end] += RNG.uniform(0.003, 0.01)

    close = start_price * np.exp(np.cumsum(shocks))
    daily_range_pct = np.abs(RNG.normal(0.012, 0.006, n))
    high = close * (1 + daily_range_pct)
    low = close * (1 - daily_range_pct)
    open_ = low + (high - low) * RNG.uniform(0.2, 0.8, n)
    volume = RNG.integers(500_000, 5_000_000, n)

    return pd.DataFrame(
        {
            "Date": dates,
            "Symbol": symbol,
            "Open": open_,
            "High": np.maximum.reduce([high, open_, close]),
            "Low": np.minimum.reduce([low, open_, close]),
            "Close": close,
            "Adj_Close": close,
            "Volume": volume,
            "Data_Source": "SYNTHETIC_DEMO",
        }
    )


def main() -> None:
    end_date = datetime.today().date()
    start_date = end_date - timedelta(days=365 * 5)
    start, end = start_date.isoformat(), end_date.isoformat()

    # Rough starting prices / vol in the ballpark of real NSE large-caps,
    # for a plausible-looking demo -- not fitted to any real data.
    symbols = {
        "RELIANCE": dict(start_price=2400, annual_drift=0.14, annual_vol=0.28),
        "TCS": dict(start_price=3300, annual_drift=0.11, annual_vol=0.24),
        "HDFCBANK": dict(start_price=1550, annual_drift=0.10, annual_vol=0.26),
        "INFY": dict(start_price=1450, annual_drift=0.12, annual_vol=0.27),
        "ITC": dict(start_price=400, annual_drift=0.09, annual_vol=0.22),
        "NIFTY50": dict(start_price=17500, annual_drift=0.12, annual_vol=0.18),
    }

    for symbol, params in symbols.items():
        df = generate_one_symbol(symbol, start, end, **params)
        out_path = SAMPLE_DIR / f"{symbol}_SYNTHETIC_{start}_{end}.csv"
        df.to_csv(out_path, index=False)
        print(f"Wrote {len(df)} synthetic rows -> {out_path}")


if __name__ == "__main__":
    main()
