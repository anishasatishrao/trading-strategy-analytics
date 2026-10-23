"""Stage 4b: transformation and feature engineering.

Reads the validated combined CSV and adds the rolling-window features the
backtest needs. The rolling windows use .shift(1) before .rolling(...) so
that the feature for day T only looks at sessions strictly before T --
this is what "no look-ahead bias" means mechanically, and it's the single
most important correctness property of this whole pipeline.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from src import storage
from src.utils import PROJECT_ROOT, get_logger, load_config

logger = get_logger(__name__)


def add_features(df: pd.DataFrame, breakout_lookback: int, exit_lookback: int) -> pd.DataFrame:
    """df must contain one symbol's data, sorted by Date ascending."""
    df = df.sort_values("Date").reset_index(drop=True).copy()

    if "Adj_Close" not in df.columns or df["Adj_Close"].isna().all():
        df["Adj_Close"] = df["Close"]

    # shift(1): only completed, prior sessions are visible when the
    # signal for "today" is computed.
    df["rolling_high_breakout"] = df["Close"].shift(1).rolling(breakout_lookback).max()
    df["rolling_low_exit"] = df["Close"].shift(1).rolling(exit_lookback).min()

    df["daily_return"] = df["Adj_Close"].pct_change()
    df["buy_signal"] = df["Close"] > df["rolling_high_breakout"]
    df["exit_signal"] = df["Close"] < df["rolling_low_exit"]

    return df


def main() -> None:
    parser = argparse.ArgumentParser(description="Transform validated data into analytical features.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "settings.yaml"))
    parser.add_argument("--skip-minio", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    data_cfg = cfg["data"]
    strategy_cfg = cfg["strategy"]
    processed_dir = PROJECT_ROOT / data_cfg["processed_dir"]

    validated_path = processed_dir / "validated_combined.csv"
    if not validated_path.exists():
        logger.error(f"{validated_path} not found. Run validate_data.py first.")
        raise SystemExit(1)

    combined = pd.read_csv(validated_path, parse_dates=["Date"])

    transformed_frames = []
    for symbol, group in combined.groupby("Symbol"):
        transformed_frames.append(
            add_features(group, strategy_cfg["breakout_lookback_days"], strategy_cfg["exit_lookback_days"])
        )
    transformed = pd.concat(transformed_frames, ignore_index=True)

    out_path = processed_dir / "features.parquet"
    transformed.to_parquet(out_path, index=False)
    logger.info(f"Wrote transformed features: {out_path} ({len(transformed)} rows)")

    if not args.skip_minio:
        try:
            client = storage.get_client()
            storage.upload_file(client, cfg["storage"]["processed_bucket"], out_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not upload processed file to MinIO ({exc}). Continuing without it.")


if __name__ == "__main__":
    main()
