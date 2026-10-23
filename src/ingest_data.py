"""Stage 3: historical data ingestion.

Downloads daily OHLCV data for the configured symbols + benchmark via
yfinance and writes it to data/raw/ as CSV. Also uploads a copy to the
MinIO raw bucket.

Safe to rerun: each run re-downloads the same symbol/date-range and
overwrites that specific raw file (this is NOT the same as overwriting
raw data with cleaned data — the raw layer only ever contains raw,
unmodified OHLCV pulls). If yfinance is unavailable, the script falls
back to whatever CSV already exists in data/raw/ for that symbol, so the
rest of the pipeline keeps working offline.
"""
from __future__ import annotations

import argparse
import glob
import shutil
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

from src import storage
from src.utils import PROJECT_ROOT, get_logger, load_config

logger = get_logger(__name__)


def raw_csv_path(raw_dir: Path, symbol: str, start: str, end: str) -> Path:
    return raw_dir / f"{symbol}_{start}_{end}.csv"


def download_symbol(ticker: str, start: str, end: str, retries: int = 3, backoff_seconds: float = 10.0) -> pd.DataFrame:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
            if not df.empty:
                break
            last_exc = ValueError(f"yfinance returned no data for {ticker}")
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
        if attempt < retries:
            logger.warning(f"Attempt {attempt}/{retries} failed for {ticker} ({last_exc}); retrying in {backoff_seconds}s")
            time.sleep(backoff_seconds)
    else:
        raise last_exc  # type: ignore[misc]
    if df.empty:
        raise last_exc or ValueError(f"yfinance returned no data for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df.columns = [str(c).strip().replace(" ", "_") for c in df.columns]
    rename_map = {"Adj_Close": "Adj_Close", "Date": "Date"}
    return df


def ingest_one(symbol: str, ticker: str, start: str, end: str, raw_dir: Path) -> Path:
    out_path = raw_csv_path(raw_dir, symbol, start, end)
    try:
        df = download_symbol(ticker, start, end)
        df.insert(1, "Symbol", symbol)
        df.to_csv(out_path, index=False)
        logger.info(f"Ingested {symbol} ({ticker}): {len(df)} rows -> {out_path}")
    except Exception as exc:  # noqa: BLE001 - we deliberately fall back on any failure
        if out_path.exists():
            logger.warning(f"yfinance failed for {symbol} ({exc}); using existing raw CSV {out_path}")
        else:
            logger.error(f"yfinance failed for {symbol} ({exc}) and no fallback CSV exists at {out_path}")
            raise
    return out_path


def use_sample_data(data_cfg: dict, raw_dir: Path) -> list[Path]:
    """Copies the clearly-labeled SYNTHETIC demo CSVs from data/sample/ into
    data/raw/, unchanged (filenames keep the SYNTHETIC tag and the
    Data_Source column stays set to SYNTHETIC_DEMO), so the rest of the
    pipeline has something real to run against when yfinance is
    unreachable. This NEVER silently stands in for genuine market data --
    every downstream report/dashboard view surfaces Data_Source."""
    sample_dir = PROJECT_ROOT / "data" / "sample"
    symbols = data_cfg["symbols"] + [data_cfg["benchmark_symbol"]]
    paths = []
    for symbol in symbols:
        matches = sorted(glob.glob(str(sample_dir / f"{symbol}_SYNTHETIC_*.csv")))
        if not matches:
            logger.error(f"No synthetic sample file found for {symbol} in {sample_dir}. Run data/sample/generate_synthetic_data.py first.")
            continue
        dest = raw_dir / Path(matches[-1]).name
        shutil.copy(matches[-1], dest)
        logger.warning(f"Using SYNTHETIC DEMO data for {symbol} (not real market data): {dest}")
        paths.append(dest)
    return paths


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest historical OHLCV data.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "settings.yaml"))
    parser.add_argument("--skip-minio", action="store_true", help="Skip uploading to MinIO (e.g. if it isn't running).")
    parser.add_argument(
        "--use-sample", action="store_true",
        help="Use the SYNTHETIC demo data in data/sample/ instead of calling yfinance "
             "(e.g. when the network has no access to Yahoo Finance).",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    data_cfg = cfg["data"]
    raw_dir = PROJECT_ROOT / data_cfg["raw_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)

    if args.use_sample:
        paths = use_sample_data(data_cfg, raw_dir)
        logger.info(f"Sample-data ingestion complete. {len(paths)} SYNTHETIC files in {raw_dir}")
        return

    end_date = datetime.today().date()
    start_date = end_date - timedelta(days=365 * data_cfg["period_years"])
    start, end = start_date.isoformat(), end_date.isoformat()

    paths: list[Path] = []
    all_symbols = [(s, f"{s}{data_cfg['yfinance_suffix']}") for s in data_cfg["symbols"]]
    all_symbols.append((data_cfg["benchmark_symbol"], data_cfg["benchmark_yfinance_ticker"]))

    for i, (symbol, ticker) in enumerate(all_symbols):
        paths.append(ingest_one(symbol, ticker, start, end, raw_dir))
        if i < len(all_symbols) - 1:
            time.sleep(2)  # space out requests to reduce Yahoo Finance rate-limiting

    if not args.skip_minio:
        try:
            client = storage.get_client()
            bucket = cfg["storage"]["raw_bucket"]
            for p in paths:
                storage.upload_file(client, bucket, p)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not upload raw files to MinIO ({exc}). Continuing without it.")

    logger.info(f"Ingestion complete. {len(paths)} raw files in {raw_dir}")


if __name__ == "__main__":
    main()
