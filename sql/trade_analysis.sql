-- Win rate, average profit/loss per completed trade, and the cost impact.
-- Answers: "What percentage of completed trades were profitable?",
-- "What is the average profit or loss per completed trade?", and
-- "How much did transaction costs reduce performance?"

WITH trades AS (
    SELECT
        regexp_extract(filename, 'trades_(.*)\.parquet', 1) AS symbol,
        *
    FROM read_parquet('data/processed/trades_*.parquet', filename = true)
    WHERE outcome != 'OPEN'
)
SELECT
    symbol,
    COUNT(*) AS completed_trades,
    SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) AS winning_trades,
    SUM(CASE WHEN outcome = 'LOSS' THEN 1 ELSE 0 END) AS losing_trades,
    ROUND(100.0 * SUM(CASE WHEN outcome = 'WIN' THEN 1 ELSE 0 END) / COUNT(*), 2) AS win_rate_pct,
    ROUND(AVG(net_pnl), 2) AS avg_net_pnl_per_trade,
    ROUND(SUM(gross_pnl), 2) AS total_gross_pnl,
    ROUND(SUM(estimated_costs), 2) AS total_transaction_costs,
    ROUND(SUM(net_pnl), 2) AS total_net_pnl,
    -- how much of gross profit was eaten by costs, as a percentage
    ROUND(100.0 * SUM(estimated_costs) / NULLIF(SUM(gross_pnl), 0), 2) AS costs_as_pct_of_gross_pnl
FROM trades
GROUP BY symbol
ORDER BY symbol;
