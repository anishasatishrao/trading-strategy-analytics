import pandas as pd

from src.calculate_kpis import calculate_annualized_return, calculate_monthly_returns


def test_daily_return_calculation():
    values = pd.Series([100.0, 110.0, 99.0])
    returns = values.pct_change()
    assert returns.iloc[0] != returns.iloc[0]  # NaN for first day
    assert round(returns.iloc[1], 4) == 0.10
    assert round(returns.iloc[2], 4) == -0.10


def test_cumulative_return_calculation():
    values = pd.Series([100.0, 110.0, 121.0])
    cumulative_pct = (values / values.iloc[0] - 1) * 100
    assert round(cumulative_pct.iloc[-1], 2) == 21.0


def test_monthly_returns_grouped_correctly():
    dates = pd.date_range("2024-01-01", "2024-03-31", freq="D")
    # simple deterministic series: value grows by 1 per day
    values = [100.0 + i for i in range(len(dates))]
    history_df = pd.DataFrame(
        {
            "Date": dates,
            "portfolio_value": values,
            "benchmark_value": values,
        }
    )
    monthly = calculate_monthly_returns(history_df)
    assert len(monthly) == 3
    assert monthly["strategy_monthly_return_pct"].iloc[0] != monthly["strategy_monthly_return_pct"].iloc[0]  # NaN
    # Jan 31 value / (implicit prior month baseline not present) -> first row NaN, rest computed
    assert monthly["strategy_monthly_return_pct"].iloc[1] > 0


def test_annualized_return_gated_for_short_periods():
    result = calculate_annualized_return(total_return_pct=10.0, num_calendar_days=100)
    assert result["annualized_return_pct"] is None
    assert result["reliable"] is False


def test_annualized_return_computed_for_long_periods():
    # 100% return over exactly 2 years -> CAGR should be about 41.4%
    result = calculate_annualized_return(total_return_pct=100.0, num_calendar_days=730)
    assert result["reliable"] is True
    assert 40.0 < result["annualized_return_pct"] < 43.0
