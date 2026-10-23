# Trading Strategy Performance & Risk Analytics

A local analytics platform that backtests a simple historical trend-breakout
trading strategy on Indian equities and reports both return **and** risk —
most importantly, **maximum drawdown**: how much money an investor could
have lost at the worst point in history before the strategy recovered.

This is a **historical analysis / educational project**. It does not place
live trades, does not connect to a brokerage, and does not use real money.
Past backtest results never guarantee future performance.

## 1. Business Problem

A strategy can look profitable on a total-return chart while still exposing
an investor to a large, painful decline along the way. Total profit alone
doesn't tell you whether you could have stomached the ride. This project
gives a repeatable way to check: historical returns, how that compares to
simply buying and holding the stock, how deep the worst drawdown was, how
consistent monthly results were, and how much of the profit transaction
costs ate up.

## 2. Project Objective

Answer: *"Does this trading strategy generate consistent returns, and how
much money could an investor lose during its worst historical decline?"*

## 3. Intended Users

Learners and analysts evaluating a rule-based strategy for educational
purposes, and an instructor reviewing the project. Not for professional
trading decisions.

## 4. Primary KPI — Maximum Drawdown (%)

```
Running Peak(t)   = max(Portfolio Value) seen up to and including day t
Drawdown(t)        = (Portfolio Value(t) / Running Peak(t) - 1) * 100
Maximum Drawdown   = min(Drawdown) over the whole period
```

**Representation convention (used consistently everywhere in this
project):** the drawdown **time series** is shown as a **negative** number
(how far below the peak you currently are). The **KPI card** reports the
single worst drawdown as a **positive magnitude** (e.g. "18.18%" meaning
you were 18.18% below the prior peak at the worst point).

Worked example from the spec: peak ₹1,10,000 → trough ₹90,000 →
`(90000/110000 - 1) * 100 = -18.18%` → reported as **18.18%** max drawdown.

## 5. Supporting KPIs

| KPI | Formula / meaning | Limitation |
|---|---|---|
| Initial capital | Configured starting cash | — |
| Final portfolio value | Cash + mark-to-market position value at the last date | Includes an open position's current value even though it hasn't been sold |
| Total strategy return % | `(final/initial - 1) * 100` | — |
| Benchmark return % | Buy-and-hold on the same symbol, same capital, same period | — |
| Excess return (pp) | Strategy return − benchmark return | — |
| Max drawdown % | See above | — |
| Win rate % | `winning completed trades / completed trades * 100` | Excludes any position still open at period end |
| Completed trades | Count of trades with both an entry and an exit | An open position is never counted here |
| Avg winning/losing trade % | Mean of `net_pnl / (entry_price * qty) * 100` for wins/losses | Small sample sizes can make the average noisy |
| Gross profit / gross loss | Sum of gross P&L for winners / losers, before costs | — |
| Transaction costs | Sum of entry + exit costs across completed trades | Slippage is a modeling assumption, not a guarantee of real fills |
| Monthly return | Month-end portfolio value vs. prior month-end | — |
| Annualized return | CAGR, only shown when the evaluation period ≥ 365 days | Explicitly withheld (shown as "not reliable") for shorter periods |

## 6. Dataset Source & Acquisition

**Primary source:** [Yahoo Finance](https://finance.yahoo.com/) via the
[`yfinance`](https://pypi.org/project/yfinance/) Python package, using NSE
ticker suffixes (`RELIANCE.NS`, `TCS.NS`, …) and `^NSEI` for the Nifty 50
benchmark.

**Why not NSE India directly:** [nseindia.com](https://www.nseindia.com/)
has no public, documented API, actively blocks automated scraping, and its
exact terms for redistributing historical bhavcopy data are not published
anywhere I could verify. Third-party NSE-scraping libraries (`jugaad-data`,
`nsepy`, `bhavkit`) exist but inherit that same unclear-terms problem and
maintenance risk. Yahoo Finance via `yfinance` was chosen instead as the
simpler, better-documented option for this learning project.

**Fallback:** `src/ingest_data.py --use-sample` copies clearly-labeled
**synthetic demonstration data** (see below) so the pipeline keeps working
without internet access.

### A known limitation I ran into (and how it's handled)

While building this, Yahoo Finance rate-limited (`YFRateLimitError`) every
request from this build environment's IP address, even after retries with
backoff and spacing requests out. This is an environment/network
limitation, not a bug in the ingestion code — `src/ingest_data.py`'s retry
logic and CSV-fallback logic are real and tested. **On a normal machine
with ordinary internet access, `python -m src.ingest_data` should pull real
Yahoo Finance data without this problem.** If you hit the same rate limit,
wait a few minutes and retry, or use `--use-sample`.

Because of this, the demo in this environment runs on synthetic data,
generated by `data/sample/generate_synthetic_data.py` and clearly labeled
with a `Data_Source = SYNTHETIC_DEMO` column and a `_SYNTHETIC_` tag in
every filename. **It is not real market data and the dashboard shows a
visible warning whenever it's in use.** It exists only to prove the
pipeline, backtest, SQL, and dashboard all work correctly end-to-end.

## 7. Data Dictionary

| Field | Type | Stage introduced | Notes |
|---|---|---|---|
| Date | DATE | raw | Trading day; weekends/holidays are simply absent, not missing |
| Symbol | VARCHAR | raw | NSE ticker without the `.NS` suffix |
| Open, High, Low, Close | DOUBLE | raw | Unadjusted exchange prices |
| Adj_Close | DOUBLE | raw | Dividend/split-adjusted; used for return math |
| Volume | BIGINT | raw | Validated non-negative |
| Data_Source | VARCHAR | raw (synthetic path only) | `SYNTHETIC_DEMO` when using sample data; absent for real yfinance pulls |
| rolling_high_breakout | DOUBLE | transform | `Close.shift(1).rolling(20).max()` — strictly prior sessions only |
| rolling_low_exit | DOUBLE | transform | `Close.shift(1).rolling(10).min()` |
| buy_signal / exit_signal | BOOL | transform | Derived from the two rolling columns above |
| daily_return | DOUBLE | transform | `Adj_Close.pct_change()` |
| portfolio_value, cash_balance, shares_held | — | backtest | Daily portfolio history |
| running_peak, drawdown_pct | DOUBLE | backtest | See KPI section |
| benchmark_value, benchmark_daily_return | DOUBLE | backtest | Buy-and-hold comparison |

## 8. Architecture

```
yfinance (or --use-sample synthetic CSVs)
        |
        v
src/ingest_data.py  ->  data/raw/*.csv            (immutable raw pulls)
        |
        v
src/validate_data.py -> data-quality report + data/processed/validated_combined.csv
        |
        v
MinIO "raw" bucket   (boto3 upload -- audit copy, see Section 9)
        |
        v
src/transform_data.py -> data/processed/features.parquet (rolling windows, shift(1))
        |
        v
MinIO "processed" bucket (boto3 upload)
        |
        v
src/backtest.py -> portfolio_history_<symbol>.parquet, trades_<symbol>.parquet, summary_<symbol>.json
        |
        v
src/calculate_kpis.py -> monthly_returns_<symbol>.parquet, annualized KPI
        |
        v
DuckDB reads the local Parquet files directly  ->  sql/*.sql analytics
        |
        v
Streamlit + Plotly dashboard (app/dashboard.py)
```

## 9. MinIO ↔ DuckDB Integration Decision

DuckDB in this project **never reads from MinIO over the network**.
`src/storage.py` uses `boto3` to push local files to MinIO (as a genuine,
inspectable object-storage copy of the raw/processed layers) and to pull
them back down. DuckDB always queries the **local** Parquet file. This was
chosen over configuring DuckDB's `httpfs` S3 secret directly against MinIO
because it keeps the query path fast, deterministic, and simple to debug —
MinIO's job here is demonstrating the object-storage *pattern*, not being a
live query backend.

## 10. Technology Stack

Python 3.12 · pandas · yfinance · DuckDB · PyArrow (Parquet) · MinIO · boto3
· Streamlit · Plotly · PyYAML · pytest · Docker Compose.

## 11. Repository Structure

```
trading-strategy-analytics/
├── app/dashboard.py
├── config/settings.yaml
├── data/{raw,processed,sample}/
├── sql/*.sql
├── src/{ingest_data,validate_data,transform_data,backtest,calculate_kpis,storage,utils}.py
├── tests/test_*.py
├── .env.example, .gitignore, docker-compose.yml, Dockerfile, requirements.txt, pytest.ini
```

**One deviation from the originally sketched structure:** `src/utils.py`
was added (not in the original sketch) to hold the config-loading and
logging setup every other script needs — a small, justified addition
rather than duplicating that code five times.

## 12. Prerequisites

- Python 3.12+ (tested with 3.12.3)
- Docker + Docker Compose, if you want the containerized version
- Internet access to reach Yahoo Finance for real data (optional — sample
  data works offline)

## 13. Environment Setup

```bash
cd trading-strategy-analytics
python3 -m venv venv
source venv/bin/activate        # on Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # edit if you want non-default MinIO credentials
```

## 14. Running Locally (no Docker)

```bash
# 1. Ingest data -- real data:
python -m src.ingest_data --skip-minio
# ...or, if Yahoo Finance is rate-limited / you have no internet:
python data/sample/generate_synthetic_data.py
python -m src.ingest_data --use-sample --skip-minio

# 2. Validate
python -m src.validate_data

# 3. Transform / feature engineering
python -m src.transform_data --skip-minio

# 4. Backtest + KPIs, once per symbol you want to see
python -m src.backtest --symbol RELIANCE
python -m src.calculate_kpis --symbol RELIANCE
# repeat for TCS, HDFCBANK, INFY, ITC to populate the dashboard's symbol picker

# 5. Launch the dashboard
streamlit run app/dashboard.py
# open http://localhost:8501
```

Drop `--skip-minio` from steps 1 and 3 once MinIO is running (see below) to
also push copies of the raw/processed files into object storage.

## 15. Running with Docker Compose (MinIO + Dashboard)

```bash
cp .env.example .env
docker compose up -d --build

# Run the pipeline INSIDE the dashboard container so it writes through the
# shared ./data volume and can also reach MinIO by its service name:
docker compose exec dashboard python data/sample/generate_synthetic_data.py   # or skip if using real data
docker compose exec dashboard python -m src.ingest_data --use-sample          # drop --use-sample for real yfinance data
docker compose exec dashboard python -m src.validate_data
docker compose exec dashboard python -m src.transform_data
docker compose exec dashboard python -m src.backtest --symbol RELIANCE
docker compose exec dashboard python -m src.calculate_kpis --symbol RELIANCE
# repeat the last two for TCS, HDFCBANK, INFY, ITC

docker compose restart dashboard   # picks up the newly written data/processed files
```

- Dashboard: http://localhost:8501
- MinIO console: http://localhost:9001 (login with the credentials in `.env`)

Shut down with:

```bash
docker compose down          # stops containers, keeps the MinIO volume
docker compose down -v       # also deletes the MinIO volume's data
```

This exact sequence was run and verified while building this project:
containers built and started, MinIO reported healthy, the dashboard
answered HTTP 200 and `/healthz` returned `ok`, the pipeline ran inside the
container and uploaded `features.parquet` to the `trading-processed`
MinIO bucket, and the dashboard served correctly after a restart.

## 16. Deploying to Streamlit Community Cloud

Streamlit Community Cloud only clones this GitHub repo and runs
`streamlit run app/dashboard.py` — it has no MinIO, no Docker Compose, and
no prior pipeline run. Two things make this still work out of the box:

1. The demo backtest outputs (`data/processed/*.parquet` and
   `summary_*.json`, generated from the committed SYNTHETIC sample data in
   `data/sample/`) are committed to this repo for exactly this reason —
   normally generated/reproducible outputs wouldn't be committed, but a
   hosted dashboard needs *something* to read on first load.
2. As a safety net, `app/dashboard.py` checks for those files on startup
   and regenerates them from the synthetic sample data automatically if
   they're ever missing (it never calls yfinance automatically, since a
   hosted environment's outbound network behavior isn't guaranteed).

**Steps:**

1. Push this repo to GitHub (see Section 25, "Git & Pushing to GitHub", below).
2. Go to [share.streamlit.io](https://share.streamlit.io) and sign in with
   GitHub.
3. Click "New app", pick this repo and the `main` branch.
4. Set the main file path to `app/dashboard.py`.
5. Deploy. First load may take a few extra seconds if it has to regenerate
   the demo outputs; subsequent loads are instant.

The deployed dashboard runs on the labeled SYNTHETIC demo data by default.
To see it on real data, run the pipeline locally with real yfinance data
(Section 14), commit the resulting `data/processed/` files, and redeploy.

## 17. Running the SQL Analytics

```bash
# from the project root, with the venv activated
python -c "import duckdb; print(duckdb.sql(open('sql/performance_summary.sql').read()).df())"
# or with the DuckDB CLI:
duckdb -c ".read sql/drawdown_analysis.sql"
```

Each file in `sql/` is documented at the top with the business question it
answers. `performance_summary.sql` recomputes total return and max
drawdown independently in SQL — in this project's test run it matched the
Python-computed values to the cent, which is a useful cross-check.

## 18. Running Tests

```bash
pytest tests/ -v
```

23 tests, all passing as of this writing, covering: data validation (valid
data passes; duplicates, invalid prices, bad dates, inverted high/low, and
negative volume are all rejected with a reason), return/drawdown math
(including the exact worked example from the KPI spec), and backtest
correctness (no look-ahead bias in the rolling-window features, entry
executes on the next bar's open rather than the signal day's close,
transaction costs measurably reduce net P&L, an unclosed position at the
end is excluded from completed-trade stats but still marked-to-market, and
the benchmark starts from the same capital as the strategy).

## 19. Example Analytical Questions

- What is the cumulative return of the breakout strategy on RELIANCE, and
  how does it compare to just buying and holding RELIANCE?
- What was the single worst drawdown, and when did it happen?
- Which month produced the best and worst strategy returns?
- What fraction of trades were profitable, and how concentrated was the
  profit in a handful of trades?
- How much of the gross profit did transaction costs consume?

## 20. How to Interpret the Charts

- **Portfolio Performance**: two lines from the same starting capital — if
  the strategy line is below the benchmark line, buy-and-hold would have
  done better over that period.
- **Drawdown**: always ≤ 0; the lowest point is the worst historical
  decline, marked with a dot.
- **Monthly Performance**: green bars are positive months, red are
  negative — look for consistency, not just the total.

## 21. Sample Findings (from the synthetic demo data in this repository)

Generated from the actual `data/processed/summary_*.json` files produced in
this build (synthetic data — not evidence about real NSE stocks):

| Symbol | Total Return | Benchmark Return | Max Drawdown | Win Rate | Completed Trades |
|---|---|---|---|---|---|
| RELIANCE | 28.6% | 232.8% | 39.7% | 42.9% | 28 |
| TCS | 80.0% | 336.7% | 24.2% | 42.9% | 35 |
| HDFCBANK | 84.0% | 121.0% | 22.6% | 40.7% | 27 |
| INFY | 310.3% | 1102.6% | 20.4% | 50.0% | 30 |
| ITC | 211.8% | 538.3% | 29.0% | 46.4% | 28 |

In this synthetic run, buy-and-hold beat the breakout strategy on every
symbol — a real, data-driven outcome (not hard-coded), illustrating exactly
why the dashboard never assumes the strategy wins and instead states
whichever side the numbers actually favor.

## 22. Known Limitations

- NSE's own terms for historical data redistribution could not be verified
  from public sources; Yahoo Finance was used instead for that reason.
- Yahoo Finance rate-limited this build environment outright; real-data
  ingestion should be re-run on a machine with normal, unthrottled internet
  access.
- Single-stock backtesting only; no multi-stock portfolio support yet.
- No interest on idle cash; no shorting; no leverage.
- Slippage and transaction costs are fixed-percentage assumptions, not
  modeled from an order book.
- Dividends are approximated via Adjusted Close, not modeled as discrete
  cash events.

## 23. Assumptions (full list also documented as a docstring in `src/backtest.py`)

Signal timing (shift(1) rolling windows), execution timing (next bar's
open), execution price (that open, adjusted by slippage), position sizing
(configurable fraction of cash, one position at a time), transaction costs
(percentage of notional on entry and exit), benchmark construction
(buy-and-hold, same capital, Adjusted Close), cash (earns no interest), and
missing observations (no interpolation — only days present in the cleaned
dataset are traded).

## 24. Future Improvements

- Multi-stock portfolio backtesting with capital allocation across symbols.
- A configurable short-selling / long-short mode.
- Pulling NSE-direct data once a clear, permitted access method is found.
- Parameter sweeps (vary lookback windows) with a results comparison view.
- Interest on idle cash and a more realistic slippage model.

## 25. Git & Pushing to GitHub

```bash
git remote add origin <your-repo-url>
git push -u origin main
```

If the remote already has commits, pull/rebase first:

```bash
git pull --rebase origin main
git push -u origin main
```

## 26. Financial Risk Disclaimer

This project is for educational purposes only. It analyzes historical data
and does not place real trades, connect to any brokerage, or use real
money. Past backtested performance — especially on synthetic demonstration
data — does not predict or guarantee future results. Nothing here is
investment advice.
