import pandas as pd

from src.backtest import run_backtest


def test_running_peak_and_drawdown_known_example():
    # Peak 110,000 -> trough 90,000 => drawdown ~ -18.18% (the example from the project spec)
    values = pd.Series([100_000, 110_000, 95_000, 90_000, 100_000])
    running_peak = values.cummax()
    drawdown_pct = (values / running_peak - 1) * 100
    assert running_peak.tolist() == [100_000, 110_000, 110_000, 110_000, 110_000]
    assert round(drawdown_pct.iloc[3], 2) == -18.18
    assert round(abs(drawdown_pct.min()), 2) == 18.18


def test_max_drawdown_is_minimum_of_drawdown_series():
    values = pd.Series([100.0, 120.0, 90.0, 130.0, 80.0])
    running_peak = values.cummax()
    drawdown_pct = (values / running_peak - 1) * 100
    max_drawdown_magnitude = abs(drawdown_pct.min())
    # worst decline is from peak 130 to trough 80 => (80/130 - 1)*100 ~ -38.46%
    assert round(max_drawdown_magnitude, 2) == 38.46


def test_no_drawdown_when_monotonically_increasing():
    values = pd.Series([100.0, 105.0, 110.0, 120.0])
    running_peak = values.cummax()
    drawdown_pct = (values / running_peak - 1) * 100
    assert drawdown_pct.max() == 0.0
    assert abs(drawdown_pct.min()) == 0.0


def test_backtest_drawdown_tracks_a_held_position_price_decline():
    # Buy on day 2 (signal fires day 1, next-bar-open execution), hold
    # through a rise then a fall, never exit. The portfolio's drawdown
    # should mirror the price decline once the position is held.
    closes = [100.0, 101.0, 120.0, 90.0, 95.0]
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    df = pd.DataFrame(
        {
            "Date": dates,
            "Open": closes,
            "Close": closes,
            "Adj_Close": closes,
            "buy_signal": [True, False, False, False, False],
            "exit_signal": [False, False, False, False, False],
        }
    )
    history_df, trades_df = run_backtest(
        df, symbol="TEST", initial_capital=10_000.0,
        transaction_cost_pct=0.0, slippage_pct=0.0,
    )
    peak_idx = history_df["portfolio_value"].idxmax()
    trough_idx = history_df["portfolio_value"].iloc[peak_idx:].idxmin()
    assert trough_idx > peak_idx  # the trough comes after the peak
    assert history_df["drawdown_pct"].iloc[trough_idx] < 0
    assert abs(history_df["drawdown_pct"].min()) == abs(history_df["drawdown_pct"]).max()
