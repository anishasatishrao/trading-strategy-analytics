import pandas as pd

from src.backtest import compute_summary, run_backtest
from src.transform_data import add_features


def make_df(closes: list[float], opens: list[float] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "Date": dates,
            "Open": opens or closes,
            "Close": closes,
            "Adj_Close": closes,
        }
    )


def test_signal_generation_has_no_look_ahead_bias():
    # rolling_high_breakout for day T must only use closes strictly before T.
    closes = [10, 11, 12, 13, 14, 100, 15]  # day index 5 spikes to 100
    df = make_df(closes)
    featured = add_features(df, breakout_lookback=3, exit_lookback=3)
    # The window for day index 5 (value 100) is closes[2:5] = [12,13,14] -> max 14,
    # it must NOT include 100 itself.
    assert featured.loc[5, "rolling_high_breakout"] == 14
    # The window for day index 6 DOES now include the spike (100), proving the
    # feature only ever looks backward, never at the current or future row.
    assert featured.loc[6, "rolling_high_breakout"] == 100


def test_no_trade_opens_before_a_valid_signal():
    closes = [100.0, 101.0, 99.0, 98.0, 97.0]
    df = make_df(closes)
    df["buy_signal"] = False
    df["exit_signal"] = False
    history_df, trades_df = run_backtest(df, symbol="TEST", initial_capital=10_000.0)
    assert trades_df.empty
    assert (history_df["shares_held"] == 0).all()


def test_entry_executes_on_next_bar_open_not_signal_day_close():
    # Signal fires on day 0 (buy_signal True); entry must execute at day 1's
    # Open, not day 0's Close.
    closes = [100.0, 150.0, 160.0]
    opens = [100.0, 120.0, 155.0]  # day 1's open (120) differs from day 0's close (100)
    df = make_df(closes, opens)
    df["buy_signal"] = [True, False, False]
    df["exit_signal"] = [False, False, False]
    history_df, trades_df = run_backtest(
        df, symbol="TEST", initial_capital=10_000.0, transaction_cost_pct=0.0, slippage_pct=0.0
    )
    open_trade = trades_df.iloc[0]
    assert open_trade["entry_price"] == 120.0  # day 1's open
    assert open_trade["entry_date"] == df["Date"].iloc[1]


def test_transaction_costs_reduce_net_performance():
    closes = [100.0, 101.0, 110.0, 50.0, 51.0]
    df = make_df(closes)
    df["buy_signal"] = [True, False, False, False, False]
    df["exit_signal"] = [False, False, True, False, False]

    _, trades_no_cost = run_backtest(
        df, symbol="TEST", initial_capital=10_000.0, transaction_cost_pct=0.0, slippage_pct=0.0
    )
    _, trades_with_cost = run_backtest(
        df, symbol="TEST", initial_capital=10_000.0, transaction_cost_pct=0.02, slippage_pct=0.0
    )
    completed_no_cost = trades_no_cost[trades_no_cost["outcome"] != "OPEN"].iloc[0]
    completed_with_cost = trades_with_cost[trades_with_cost["outcome"] != "OPEN"].iloc[0]
    assert completed_with_cost["net_pnl"] < completed_no_cost["net_pnl"]


def test_completed_trades_have_valid_entry_and_exit_records():
    closes = [100.0, 101.0, 110.0, 50.0, 51.0]
    df = make_df(closes)
    df["buy_signal"] = [True, False, False, False, False]
    df["exit_signal"] = [False, False, True, False, False]
    _, trades_df = run_backtest(df, symbol="TEST", initial_capital=10_000.0)
    completed = trades_df[trades_df["outcome"] != "OPEN"]
    assert len(completed) == 1
    row = completed.iloc[0]
    assert row["entry_date"] < row["exit_date"]
    assert row["quantity"] > 0
    assert row["outcome"] in ("WIN", "LOSS")


def test_open_position_at_end_is_not_counted_as_completed_trade():
    closes = [100.0, 101.0, 110.0, 120.0]
    df = make_df(closes)
    df["buy_signal"] = [True, False, False, False]
    df["exit_signal"] = [False, False, False, False]  # never exits
    history_df, trades_df = run_backtest(df, symbol="TEST", initial_capital=10_000.0)
    summary = compute_summary(history_df, trades_df, initial_capital=10_000.0)
    assert summary["completed_trade_count"] == 0
    assert summary["open_position_at_end"] is True
    # but the open position's value is still reflected in final portfolio value
    assert history_df["shares_held"].iloc[-1] > 0


def test_benchmark_and_strategy_start_from_same_capital():
    closes = [100.0, 105.0, 95.0, 110.0]
    df = make_df(closes)
    df["buy_signal"] = [False, False, False, False]
    df["exit_signal"] = [False, False, False, False]
    history_df, _ = run_backtest(df, symbol="TEST", initial_capital=50_000.0)
    assert history_df["portfolio_value"].iloc[0] == 50_000.0
    assert history_df["benchmark_value"].iloc[0] == 50_000.0
