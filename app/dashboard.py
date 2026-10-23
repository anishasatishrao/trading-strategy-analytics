"""Stage 7: Streamlit + Plotly dashboard.

Reads processed backtest outputs (Parquet) straight from data/processed/ --
no hard-coded numbers. Filters trigger a fresh backtest run in-process
(cached by Streamlit) so the dashboard never shows stale results for a
changed configuration.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import compute_summary, run_backtest  # noqa: E402
from src.calculate_kpis import calculate_annualized_return, calculate_monthly_returns  # noqa: E402
from src.utils import load_config  # noqa: E402
from src.validate_data import load_latest_raw_csv, validate_dataframe  # noqa: E402

st.set_page_config(page_title="Trading Strategy Performance & Risk Analytics", layout="wide")

CFG = load_config()
DATA_CFG = CFG["data"]
STRATEGY_CFG = CFG["strategy"]
PROCESSED_DIR = PROJECT_ROOT / DATA_CFG["processed_dir"]
RAW_DIR = PROJECT_ROOT / DATA_CFG["raw_dir"]


def fmt_inr(value: float) -> str:
    return f"₹{value:,.2f}"


def fmt_pct(value: float, signed: bool = True) -> str:
    if value is None:
        return "N/A"
    sign = "+" if signed and value > 0 else ""
    return f"{sign}{value:.2f}%"


@st.cache_data
def load_features() -> pd.DataFrame:
    path = PROCESSED_DIR / "features.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


@st.cache_data
def run_backtest_cached(
    symbol: str, initial_capital: float, transaction_cost_pct: float, slippage_pct: float,
    start_date: str, end_date: str,
):
    features = load_features()
    symbol_df = features[features["Symbol"] == symbol].copy()
    symbol_df["Date"] = pd.to_datetime(symbol_df["Date"])
    symbol_df = symbol_df[(symbol_df["Date"] >= start_date) & (symbol_df["Date"] <= end_date)]
    if symbol_df.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    history_df, trades_df = run_backtest(
        symbol_df, symbol,
        initial_capital=initial_capital,
        position_size_pct=STRATEGY_CFG["position_size_pct"],
        transaction_cost_pct=transaction_cost_pct,
        slippage_pct=slippage_pct,
    )
    summary = compute_summary(history_df, trades_df, initial_capital)
    num_days = (history_df["Date"].max() - history_df["Date"].min()).days
    summary.update(calculate_annualized_return(summary["total_return_pct"], num_days))
    return history_df, trades_df, summary


def load_data_quality_report() -> list[dict]:
    path = PROCESSED_DIR / "data_quality_report.json"
    if not path.exists():
        return []
    with open(path) as f:
        return json.load(f)


st.title("Trading Strategy Performance & Risk Analytics")
st.caption(
    "Historical backtest of a trend-breakout strategy on Indian equities. "
    "Educational analysis only -- not investment advice, no live trading."
)

features_df = load_features()
if features_df.empty:
    st.error(
        "No processed data found. Run the pipeline first:\n\n"
        "python -m src.ingest_data --use-sample --skip-minio\n"
        "python -m src.validate_data\n"
        "python -m src.transform_data --skip-minio"
    )
    st.stop()

is_synthetic = False
quality_report = load_data_quality_report()

# ---------------------------------------------------------------- Sidebar --
st.sidebar.header("Filters & Controls")
symbol = st.sidebar.selectbox("Stock symbol", DATA_CFG["symbols"], index=0)

min_date = pd.to_datetime(features_df["Date"]).min().date()
max_date = pd.to_datetime(features_df["Date"]).max().date()
date_range = st.sidebar.date_input("Date range", value=(min_date, max_date), min_value=min_date, max_value=max_date)
start_date, end_date = (date_range if isinstance(date_range, tuple) and len(date_range) == 2 else (min_date, max_date))

initial_capital = st.sidebar.number_input(
    "Initial capital (INR)", min_value=10_000.0, max_value=10_000_000.0,
    value=float(STRATEGY_CFG["initial_capital"]), step=10_000.0,
)
transaction_cost_pct = st.sidebar.slider(
    "Transaction cost (%)", min_value=0.0, max_value=1.0,
    value=float(STRATEGY_CFG["transaction_cost_pct"]) * 100, step=0.01,
) / 100
slippage_pct = st.sidebar.slider(
    "Slippage (%)", min_value=0.0, max_value=1.0,
    value=float(STRATEGY_CFG["slippage_pct"]) * 100, step=0.01,
) / 100

st.sidebar.caption(
    f"Strategy: buy on breakout above the {STRATEGY_CFG['breakout_lookback_days']}-session high, "
    f"exit below the {STRATEGY_CFG['exit_lookback_days']}-session low. "
    "Changing a control above recalculates the backtest immediately."
)

history_df, trades_df, summary = run_backtest_cached(
    symbol, initial_capital, transaction_cost_pct, slippage_pct,
    str(start_date), str(end_date),
)

if history_df.empty:
    st.warning("No data for the selected symbol/date range.")
    st.stop()

symbol_raw = load_latest_raw_csv(RAW_DIR, symbol)
if symbol_raw is not None and "Data_Source" in symbol_raw.columns and (symbol_raw["Data_Source"] == "SYNTHETIC_DEMO").any():
    is_synthetic = True
    st.warning(
        "⚠️ SYNTHETIC DEMONSTRATION DATA -- this is NOT real NSE/Yahoo Finance market data. "
        "It was generated locally because live data access was unavailable. "
        "See the Data Quality tab and README for details.",
        icon="⚠️",
    )

# ------------------------------------------------------------------- A. Overview --
st.header("A. Overview")
cols = st.columns(4)
cols[0].metric("Initial Capital", fmt_inr(summary["initial_capital"]))
cols[1].metric("Final Portfolio Value", fmt_inr(summary["final_portfolio_value"]))
cols[2].metric("Total Return", fmt_pct(summary["total_return_pct"]))
cols[3].metric("Benchmark Return", fmt_pct(summary["benchmark_return_pct"]))

cols2 = st.columns(4)
cols2[0].metric("Max Drawdown", fmt_pct(summary["max_drawdown_pct"], signed=False), help="Reported as a positive magnitude: the largest peak-to-trough decline.")
cols2[1].metric("Win Rate", fmt_pct(summary["win_rate_pct"], signed=False))
cols2[2].metric("Completed Trades", summary["completed_trade_count"])
cols2[3].metric("Transaction Costs", fmt_inr(summary["total_transaction_costs"]))

if summary.get("open_position_at_end"):
    st.info("A position was still open at the end of the evaluation period. It is marked-to-market in the final portfolio value but excluded from completed-trade statistics.")

if summary.get("reliable"):
    st.caption(f"Annualized return: {fmt_pct(summary['annualized_return_pct'])} (CAGR over the evaluation period).")
else:
    st.caption(f"Annualized return not shown: {summary.get('reason')}")

# ------------------------------------------------------------------- B. Portfolio Performance --
st.header("B. Portfolio Performance")
fig = go.Figure()
fig.add_trace(go.Scatter(x=history_df["Date"], y=history_df["portfolio_value"], name="Strategy", line=dict(color="#2E86AB")))
fig.add_trace(go.Scatter(x=history_df["Date"], y=history_df["benchmark_value"], name="Buy & Hold Benchmark", line=dict(color="#A23B72", dash="dash")))
fig.update_layout(xaxis_title="Date", yaxis_title="Portfolio Value (INR)", hovermode="x unified", legend=dict(orientation="h"))
st.plotly_chart(fig, use_container_width=True)

# ------------------------------------------------------------------- C. Drawdown --
st.header("C. Drawdown Analysis")
st.markdown(
    "**Maximum drawdown** is the largest percentage decline from a previous portfolio peak to a "
    "later low point. It answers: *if you had invested at the worst possible moment, how much of "
    "your money could you have temporarily lost before it recovered?* The chart below shows the "
    "drawdown as a **negative** value below each running peak; the KPI card above reports its "
    "magnitude as a **positive** number."
)
fig_dd = go.Figure()
fig_dd.add_trace(go.Scatter(
    x=history_df["Date"], y=history_df["drawdown_pct"], name="Drawdown %",
    fill="tozeroy", line=dict(color="#D64550"),
))
worst_idx = history_df["drawdown_pct"].idxmin()
fig_dd.add_trace(go.Scatter(
    x=[history_df["Date"].iloc[worst_idx]], y=[history_df["drawdown_pct"].iloc[worst_idx]],
    mode="markers+text", name="Worst drawdown",
    text=[f"{history_df['drawdown_pct'].iloc[worst_idx]:.2f}%"], textposition="bottom center",
    marker=dict(color="black", size=10),
))
fig_dd.update_layout(xaxis_title="Date", yaxis_title="Drawdown (%)", hovermode="x unified")
st.plotly_chart(fig_dd, use_container_width=True)

# ------------------------------------------------------------------- D. Monthly Performance --
st.header("D. Monthly Performance")
monthly = calculate_monthly_returns(history_df)
monthly_plot = monthly.dropna(subset=["strategy_monthly_return_pct"])
fig_month = go.Figure()
colors = ["#2ca02c" if v >= 0 else "#d62728" for v in monthly_plot["strategy_monthly_return_pct"]]
fig_month.add_trace(go.Bar(x=monthly_plot["month"], y=monthly_plot["strategy_monthly_return_pct"], marker_color=colors, name="Monthly Return %"))
fig_month.update_layout(xaxis_title="Month", yaxis_title="Monthly Return (%)")
st.plotly_chart(fig_month, use_container_width=True)
st.dataframe(monthly_plot.round(2), use_container_width=True)

# ------------------------------------------------------------------- E. Trade Analysis --
st.header("E. Trade Analysis")
completed_trades = trades_df[trades_df["outcome"] != "OPEN"] if not trades_df.empty else trades_df
wins = completed_trades[completed_trades["outcome"] == "WIN"] if not completed_trades.empty else completed_trades
losses = completed_trades[completed_trades["outcome"] == "LOSS"] if not completed_trades.empty else completed_trades

t_cols = st.columns(4)
t_cols[0].metric("Winning Trades", len(wins))
t_cols[1].metric("Losing Trades", len(losses))
t_cols[2].metric("Avg Winning Trade", fmt_pct(summary["avg_winning_trade_return_pct"]))
t_cols[3].metric("Avg Losing Trade", fmt_pct(summary["avg_losing_trade_return_pct"]))
st.metric("Net Profit After Costs", fmt_inr(summary["gross_profit"] + summary["gross_loss"] - summary["total_transaction_costs"]))
st.dataframe(trades_df.round(2), use_container_width=True)

# ------------------------------------------------------------------- F. Data Quality --
st.header("F. Data Quality")
st.write(f"**Dataset source:** {'SYNTHETIC DEMONSTRATION DATA (see warning above)' if is_synthetic else 'Yahoo Finance (yfinance), NSE tickers'}")
st.write(f"**Date range:** {min_date} to {max_date}")
st.write(f"**Symbols:** {', '.join(DATA_CFG['symbols'])} | Benchmark: {DATA_CFG['benchmark_symbol']}")
if quality_report:
    qdf = pd.DataFrame(quality_report)
    st.dataframe(qdf, use_container_width=True)
else:
    st.info("Run src/validate_data.py to generate the data-quality report.")

# ------------------------------------------------------------------- G. Business Insights --
st.header("G. Business Insights")
insights = []
if summary["total_return_pct"] > summary["benchmark_return_pct"]:
    insights.append(f"The strategy OUTPERFORMED the buy-and-hold benchmark by {fmt_pct(summary['excess_return_pct'])} over this period.")
else:
    insights.append(f"The strategy UNDERPERFORMED the buy-and-hold benchmark by {fmt_pct(abs(summary['excess_return_pct']), signed=False)} over this period.")

insights.append(f"The worst historical decline (maximum drawdown) was {fmt_pct(summary['max_drawdown_pct'], signed=False)} of portfolio value.")

if not completed_trades.empty:
    top_trade_pnl = completed_trades["net_pnl"].abs().max()
    total_abs_pnl = completed_trades["net_pnl"].abs().sum()
    concentration = (top_trade_pnl / total_abs_pnl * 100) if total_abs_pnl else 0
    if concentration > 30:
        insights.append(f"Profits/losses were concentrated: the single largest trade accounted for {concentration:.1f}% of total absolute P&L.")
    else:
        insights.append(f"P&L was reasonably spread across trades; the largest single trade was {concentration:.1f}% of total absolute P&L.")

if not monthly_plot.empty:
    best_month = monthly_plot.loc[monthly_plot["strategy_monthly_return_pct"].idxmax()]
    worst_month = monthly_plot.loc[monthly_plot["strategy_monthly_return_pct"].idxmin()]
    insights.append(f"Best month: {best_month['month'].strftime('%Y-%m')} ({best_month['strategy_monthly_return_pct']:.2f}%). Worst month: {worst_month['month'].strftime('%Y-%m')} ({worst_month['strategy_monthly_return_pct']:.2f}%).")

gross_total = abs(summary["gross_profit"]) + abs(summary["gross_loss"])
cost_impact_pct = (summary["total_transaction_costs"] / gross_total * 100) if gross_total else 0
insights.append(f"Transaction costs consumed approximately {cost_impact_pct:.1f}% of gross trading activity.")

for insight in insights:
    st.markdown(f"- {insight}")

st.caption(
    "All figures above are computed from this historical backtest only. They describe the past; "
    "they do not predict future performance, and this strategy has not been paper-traded or live-traded."
)
