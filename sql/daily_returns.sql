-- Daily and cumulative returns for the strategy vs. the buy-and-hold benchmark.
-- Run from the project root (so the relative glob below resolves), e.g.:
--   duckdb -c ".read sql/daily_returns.sql"
-- Answers: "What is the cumulative strategy return?" and "How does it compare
-- with the benchmark, day by day?"

WITH history AS (
    SELECT
        regexp_extract(filename, 'portfolio_history_(.*)\.parquet', 1) AS symbol,
        Date,
        portfolio_value,
        benchmark_value,
        daily_return,
        benchmark_daily_return
    FROM read_parquet('data/processed/portfolio_history_*.parquet', filename = true)
)
SELECT
    symbol,
    Date,
    portfolio_value,
    daily_return,
    -- cumulative return since day 1, as a percentage of initial capital
    (portfolio_value / FIRST(portfolio_value) OVER (PARTITION BY symbol ORDER BY Date) - 1) * 100
        AS cumulative_strategy_return_pct,
    benchmark_value,
    benchmark_daily_return,
    (benchmark_value / FIRST(benchmark_value) OVER (PARTITION BY symbol ORDER BY Date) - 1) * 100
        AS cumulative_benchmark_return_pct
FROM history
ORDER BY symbol, Date;
