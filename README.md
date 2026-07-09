# public-data-etl-pipeline

A production-grade **ETL + data-quality validation pipeline** for public economic
data from the U.S. Federal Reserve (FRED). It extracts economic time series,
transforms them into a clean tabular shape, **validates them against explicit
data-quality rules**, and loads the validated results into a local analytical
database.

## Why this exists (business framing)

Analytics and dashboards are only as trustworthy as the data feeding them. A
silent schema change, a run of missing values, an out-of-range spike, or a
duplicated record upstream can quietly corrupt every downstream chart and
decision. This pipeline puts a **validation gate between raw ingestion and the
analytics layer**: data that fails schema, null, continuity, range, or
duplicate checks is flagged in a timestamped QA report and never silently
promoted. The result is a reproducible, auditable ingestion process — the kind
of guardrail that keeps bad data out of production analytics.

## Data source

[FRED — Federal Reserve Economic Data](https://fred.stlouisfed.org/docs/api/fred/),
a free public API. Series pulled initially:

| Series ID | Description               | Frequency |
|-----------|---------------------------|-----------|
| `UNRATE`  | Civilian unemployment rate | Monthly   |
| `GDP`     | Gross Domestic Product     | Quarterly |
| `DGS10`   | 10-Year Treasury yield     | Daily     |

## Architecture

```
FRED API
   │
   ▼
 extract.py   →  pull each series, save raw JSON to data/raw/
   │
   ▼
transform.py  →  parse raw JSON into a clean DataFrame (date, series_id, value)
   │
   ▼
validate.py   →  run data-quality checks; write a markdown QA report
   │            (schema / null / date-continuity / range / duplicate)
   ▼
 load.py      →  upsert validated rows into DuckDB (data/processed/)
   │
   ▼
visualize.py  →  read the DB back out, render an HTML chart dashboard
```

Each stage is a separate, independently testable module. Transform is a pure
function (raw in → DataFrame out) and validation returns structured pass/fail
results, so both are covered by unit tests.

## Setup

1. **Get a free FRED API key**: <https://fredaccount.stlouisfed.org/apikeys>
2. **Install dependencies** (a virtual environment is recommended):
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Configure your key**:
   ```bash
   cp .env.example .env
   # then edit .env and set FRED_API_KEY
   ```
   `.env` is git-ignored and is never committed.

## Running the pipeline

```bash
python -m src            # runs extract → transform → validate → load
```

The run prints a summary: rows processed, per-series QA pass/fail, and elapsed
time. QA reports are written to `qa_reports/`.

## Visualizing the data

After a pipeline run has loaded data, generate an HTML dashboard of the loaded
series (a line chart per series with row counts and latest values):

```bash
python -m src.visualize     # writes qa_reports/dashboard_<timestamp>.html
```

Open the resulting file in any browser. It is fully self-contained (charts are
embedded), reads only from the database, and never modifies it.

## Running the tests

```bash
pytest
```

## A note on scope

This is a **portfolio project** built to demonstrate data-engineering and
data-quality practices (modular ETL, explicit validation, testing, clean git
history). It uses only free, public FRED data — no secrets, API keys, or
personal data are committed to this repository.
