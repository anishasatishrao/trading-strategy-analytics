-- Drawdown time series and the single worst historical decline per symbol.
-- Answers: "What is the maximum drawdown, and when did it happen?"
-- drawdown_pct is stored as a NEGATIVE number (below the running peak);
-- max_drawdown_pct here is reported as a POSITIVE magnitude, matching the
-- convention used in the dashboard KPI cards.

WITH history AS (
    SELECT
        regexp_extract(filename, 'portfolio_history_(.*)\.parquet', 1) AS symbol,
        Date,
        portfolio_value,
        running_peak,
        drawdown_pct
    FROM read_parquet('data/processed/portfolio_history_*.parquet', filename = true)
)
SELECT
    symbol,
    MIN(drawdown_pct) * -1 AS max_drawdown_pct,
    (ARG_MIN(Date, drawdown_pct)) AS max_drawdown_date,
    (ARG_MIN(running_peak, drawdown_pct)) AS peak_value_before_decline,
    (ARG_MIN(portfolio_value, drawdown_pct)) AS trough_value
FROM history
GROUP BY symbol
ORDER BY symbol;

-- Full drawdown series (for charting) -- uncomment to use instead of the summary above:
-- SELECT symbol, Date, portfolio_value, running_peak, drawdown_pct
-- FROM history ORDER BY symbol, Date;
