"""Stage 5: trend-breakout backtest (single stock, long-only, no leverage).

Documented assumptions (also repeated in the README):
- Signal timing: a buy signal fires on day T if Close[T] > the highest
  Close over the 20 PRIOR completed sessions (T-20..T-1). An exit signal
  fires on day T if Close[T] < the lowest Close over the 10 prior
  completed sessions. These rolling windows are computed in
  transform_data.py using .shift(1), so day T's signal never sees day T's
  own close used as part of the window, and never sees any future data.
- Execution timing: a signal generated using day T's close is executed at
  day T+1's Open ("next bar open" -- a standard way of avoiding
  look-ahead bias: you can't trade on a close price before the market
  closes).
- Execution price: Open price on the execution day, adjusted by a fixed
  slippage percentage against the trader (buys fill higher, sells fill
  lower) to represent the real-world cost of not getting a perfect fill.
- Position sizing: configurable fraction (`position_size_pct`) of
  available cash is committed per trade; default 1.0 = all available cash,
  one position at a time, no leverage, no shorting.
- Transaction costs: a fixed percentage of trade notional, applied on
  both entry and exit.
- Dividends / corporate actions: approximated via Adjusted Close for
  return calculations; the raw Close (unadjusted) is used for signal
  generation and execution price because that's the price that was
  actually quoted on the exchange that day.
- Benchmark: buy-and-hold on the benchmark's Adjusted Close, invested in
  full on the first available day, same initial capital, held for the
  full evaluation period, no rebalancing, no costs (buy-and-hold has one
  trade).
- Cash: uninvested cash earns no interest (conservative assumption).
- Missing observations: the backtest only trades on days present in the
  cleaned dataset; it does not try to fill or interpolate missing days.
- An open position still held at the end of the evaluation period is
  marked-to-market in the final portfolio value but is NOT counted as a
  completed trade (it has no exit price/date yet).
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field

import pandas as pd

from src.utils import PROJECT_ROOT, get_logger, load_config

logger = get_logger(__name__)


@dataclass
class Trade:
    trade_id: int
    symbol: str
    entry_date: pd.Timestamp
    entry_price: float
    quantity: int
    exit_date: pd.Timestamp | None = None
    exit_price: float | None = None
    entry_cost: float = 0.0
    exit_cost: float = 0.0

    @property
    def is_open(self) -> bool:
        return self.exit_date is None

    def to_dict(self) -> dict:
        if self.is_open:
            return {
                "trade_id": self.trade_id, "symbol": self.symbol,
                "entry_date": self.entry_date, "entry_price": self.entry_price,
                "exit_date": None, "exit_price": None, "quantity": self.quantity,
                "gross_pnl": None, "estimated_costs": self.entry_cost,
                "net_pnl": None, "trade_return_pct": None, "outcome": "OPEN",
            }
        gross_pnl = (self.exit_price - self.entry_price) * self.quantity
        total_costs = self.entry_cost + self.exit_cost
        net_pnl = gross_pnl - total_costs
        trade_return_pct = net_pnl / (self.entry_price * self.quantity) * 100
        return {
            "trade_id": self.trade_id, "symbol": self.symbol,
            "entry_date": self.entry_date, "entry_price": self.entry_price,
            "exit_date": self.exit_date, "exit_price": self.exit_price,
            "quantity": self.quantity, "gross_pnl": gross_pnl,
            "estimated_costs": total_costs, "net_pnl": net_pnl,
            "trade_return_pct": trade_return_pct,
            "outcome": "WIN" if net_pnl > 0 else "LOSS",
        }


def run_backtest(
    df: pd.DataFrame,
    symbol: str,
    initial_capital: float = 100_000.0,
    position_size_pct: float = 1.0,
    transaction_cost_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """df: one symbol's feature-engineered rows, sorted by Date ascending,
    with columns Close, Open, Adj_Close, buy_signal, exit_signal.

    Returns (daily_history_df, trades_df).
    """
    df = df.sort_values("Date").reset_index(drop=True)

    cash = initial_capital
    shares_held = 0
    holding = False
    pending_entry = False
    pending_exit = False
    trade_id_counter = 0
    current_trade: Trade | None = None
    trades: list[Trade] = []

    benchmark_base = None
    history_rows = []

    for i, row in df.iterrows():
        # --- execute any order queued from the previous day's signal, at today's open ---
        if pending_entry and not holding and not pd.isna(row["Open"]):
            exec_price = row["Open"] * (1 + slippage_pct)
            budget = cash * position_size_pct
            qty = math.floor(budget / exec_price)
            if qty > 0:
                cost = exec_price * qty * transaction_cost_pct
                cash -= exec_price * qty + cost
                shares_held = qty
                holding = True
                trade_id_counter += 1
                current_trade = Trade(
                    trade_id=trade_id_counter, symbol=symbol,
                    entry_date=row["Date"], entry_price=exec_price,
                    quantity=qty, entry_cost=cost,
                )
            pending_entry = False

        if pending_exit and holding and not pd.isna(row["Open"]):
            exec_price = row["Open"] * (1 - slippage_pct)
            proceeds = exec_price * shares_held
            cost = proceeds * transaction_cost_pct
            cash += proceeds - cost
            current_trade.exit_date = row["Date"]
            current_trade.exit_price = exec_price
            current_trade.exit_cost = cost
            trades.append(current_trade)
            current_trade = None
            shares_held = 0
            holding = False
            pending_exit = False

        # --- mark-to-market today ---
        position_value = shares_held * row["Close"] if holding else 0.0
        portfolio_value = cash + position_value

        if benchmark_base is None and not pd.isna(row["Adj_Close"]):
            benchmark_base = row["Adj_Close"]
        benchmark_value = (
            initial_capital * (row["Adj_Close"] / benchmark_base) if benchmark_base else initial_capital
        )

        history_rows.append(
            {
                "Date": row["Date"],
                "portfolio_value": portfolio_value,
                "cash_balance": cash,
                "shares_held": shares_held,
                "benchmark_value": benchmark_value,
            }
        )

        # --- queue new signals for tomorrow's execution, based on today's completed data ---
        if not holding and not pending_entry and bool(row.get("buy_signal", False)):
            pending_entry = True
        if holding and not pending_exit and bool(row.get("exit_signal", False)):
            pending_exit = True

    if current_trade is not None:
        trades.append(current_trade)  # still open at end of period; to_dict() marks it OPEN

    history_df = pd.DataFrame(history_rows)
    history_df["daily_return"] = history_df["portfolio_value"].pct_change()
    history_df["benchmark_daily_return"] = history_df["benchmark_value"].pct_change()
    history_df["running_peak"] = history_df["portfolio_value"].cummax()
    history_df["drawdown_pct"] = (history_df["portfolio_value"] / history_df["running_peak"] - 1) * 100

    trades_df = pd.DataFrame([t.to_dict() for t in trades])
    return history_df, trades_df


def compute_summary(history_df: pd.DataFrame, trades_df: pd.DataFrame, initial_capital: float) -> dict:
    final_value = history_df["portfolio_value"].iloc[-1]
    benchmark_final = history_df["benchmark_value"].iloc[-1]
    total_return_pct = (final_value / initial_capital - 1) * 100
    benchmark_return_pct = (benchmark_final / initial_capital - 1) * 100
    max_drawdown_pct = abs(history_df["drawdown_pct"].min())

    completed = trades_df[trades_df["outcome"] != "OPEN"] if not trades_df.empty else trades_df
    wins = completed[completed["outcome"] == "WIN"] if not completed.empty else completed
    losses = completed[completed["outcome"] == "LOSS"] if not completed.empty else completed

    win_rate = (len(wins) / len(completed) * 100) if len(completed) > 0 else 0.0
    gross_profit = wins["gross_pnl"].sum() if not wins.empty else 0.0
    gross_loss = losses["gross_pnl"].sum() if not losses.empty else 0.0
    total_costs = completed["estimated_costs"].sum() if not completed.empty else 0.0

    return {
        "initial_capital": initial_capital,
        "final_portfolio_value": final_value,
        "total_return_pct": total_return_pct,
        "benchmark_return_pct": benchmark_return_pct,
        "excess_return_pct": total_return_pct - benchmark_return_pct,
        "max_drawdown_pct": max_drawdown_pct,
        "win_rate_pct": win_rate,
        "completed_trade_count": int(len(completed)),
        "gross_profit": float(gross_profit),
        "gross_loss": float(gross_loss),
        "total_transaction_costs": float(total_costs),
        "avg_winning_trade_return_pct": float(wins["trade_return_pct"].mean()) if not wins.empty else 0.0,
        "avg_losing_trade_return_pct": float(losses["trade_return_pct"].mean()) if not losses.empty else 0.0,
        "open_position_at_end": bool((trades_df["outcome"] == "OPEN").any()) if not trades_df.empty else False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the trend-breakout backtest for one symbol.")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config" / "settings.yaml"))
    parser.add_argument("--symbol", default=None, help="Overrides strategy.default_symbol from config.")
    args = parser.parse_args()

    cfg = load_config(args.config)
    strategy_cfg = cfg["strategy"]
    data_cfg = cfg["data"]
    symbol = args.symbol or strategy_cfg["default_symbol"]

    processed_dir = PROJECT_ROOT / data_cfg["processed_dir"]
    features_path = processed_dir / "features.parquet"
    if not features_path.exists():
        logger.error(f"{features_path} not found. Run transform_data.py first.")
        raise SystemExit(1)

    features = pd.read_parquet(features_path)
    symbol_df = features[features["Symbol"] == symbol].copy()
    if symbol_df.empty:
        logger.error(f"No feature rows found for symbol {symbol}.")
        raise SystemExit(1)

    history_df, trades_df = run_backtest(
        symbol_df, symbol,
        initial_capital=strategy_cfg["initial_capital"],
        position_size_pct=strategy_cfg["position_size_pct"],
        transaction_cost_pct=strategy_cfg["transaction_cost_pct"],
        slippage_pct=strategy_cfg["slippage_pct"],
    )
    summary = compute_summary(history_df, trades_df, strategy_cfg["initial_capital"])

    history_df.to_parquet(processed_dir / f"portfolio_history_{symbol}.parquet", index=False)
    trades_df.to_parquet(processed_dir / f"trades_{symbol}.parquet", index=False)

    import json
    with open(processed_dir / f"summary_{symbol}.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info(f"Backtest complete for {symbol}.")
    for k, v in summary.items():
        logger.info(f"  {k}: {v}")


if __name__ == "__main__":
    main()
