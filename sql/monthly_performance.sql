-- Best and worst month per symbol, and the full monthly table.
-- Answers: "Which month had the best return?" / "the worst return?"

WITH monthly AS (
    SELECT
        regexp_extract(filename, 'monthly_returns_(.*)\.parquet', 1) AS symbol,
        month,
        strategy_monthly_return_pct,
        benchmark_monthly_return_pct
    FROM read_parquet('data/processed/monthly_returns_*.parquet', filename = true)
    WHERE strategy_monthly_return_pct IS NOT NULL
)
SELECT
    symbol,
    month,
    strategy_monthly_return_pct,
    benchmark_monthly_return_pct,
    CASE
        WHEN strategy_monthly_return_pct = MAX(strategy_monthly_return_pct) OVER (PARTITION BY symbol)
            THEN 'BEST_MONTH'
        WHEN strategy_monthly_return_pct = MIN(strategy_monthly_return_pct) OVER (PARTITION BY symbol)
            THEN 'WORST_MONTH'
        ELSE NULL
    END AS flag
FROM monthly
ORDER BY symbol, month;
