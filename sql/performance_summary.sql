-- One-row-per-symbol performance summary, cross-checking the Python-computed
-- summary_<symbol>.json against values recomputed independently in SQL.
-- Answers: "How does the strategy compare with the benchmark overall?"
-- and serves as a sanity check that Python and SQL agree.

WITH history AS (
    SELECT
        regexp_extract(filename, 'portfolio_history_(.*)\.parquet', 1) AS symbol,
        Date, portfolio_value, benchmark_value, drawdown_pct
    FROM read_parquet('data/processed/portfolio_history_*.parquet', filename = true)
),
agg AS (
    SELECT
        symbol,
        MIN(Date) AS start_date,
        MAX(Date) AS end_date,
        FIRST(portfolio_value ORDER BY Date) AS initial_value,
        LAST(portfolio_value ORDER BY Date) AS final_value,
        FIRST(benchmark_value ORDER BY Date) AS benchmark_initial_value,
        LAST(benchmark_value ORDER BY Date) AS benchmark_final_value,
        MIN(drawdown_pct) * -1 AS max_drawdown_pct_sql
    FROM history
    GROUP BY symbol
)
SELECT
    symbol,
    start_date,
    end_date,
    ROUND(initial_value, 2) AS initial_value,
    ROUND(final_value, 2) AS final_value,
    ROUND((final_value / initial_value - 1) * 100, 2) AS total_return_pct_sql,
    ROUND((benchmark_final_value / benchmark_initial_value - 1) * 100, 2) AS benchmark_return_pct_sql,
    ROUND(max_drawdown_pct_sql, 2) AS max_drawdown_pct_sql
FROM agg
ORDER BY symbol;
