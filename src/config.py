"""Central configuration for the ETL pipeline.

Holds the FRED API key (loaded from the environment), the set of series to
pull along with their data-quality metadata, and all filesystem paths used by
the pipeline. Keeping this in one place means the extract, transform,
validate, and load stages share a single source of truth.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load variables from a local `.env` file into the environment, if present.
# `.env` is git-ignored; in CI the value is supplied as a real env var instead.
load_dotenv()

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

#: FRED API key, read from the environment. May be ``None`` if unset; the
#: extract stage validates its presence before making any request so that
#: importing this module never fails (e.g. during unit tests).
FRED_API_KEY: str | None = os.getenv("FRED_API_KEY")

#: Base URL for the FRED "series/observations" endpoint.
FRED_BASE_URL: str = "https://api.stlouisfed.org/fred/series/observations"


# ---------------------------------------------------------------------------
# Series definitions
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeriesConfig:
    """Data-quality metadata for a single FRED series.

    Attributes:
        series_id: The FRED series identifier (e.g. ``"UNRATE"``).
        description: Human-readable name, used in QA reports.
        frequency: Expected cadence — one of ``"monthly"``, ``"quarterly"``,
            or ``"daily"``. Drives the date-continuity check.
        min_value: Lowest plausible value; anything below is flagged.
        max_value: Highest plausible value; anything above is flagged.
    """

    series_id: str
    description: str
    frequency: str
    min_value: float
    max_value: float


#: The series pulled by the pipeline, keyed by series ID. Ranges are
#: deliberately wide plausibility bounds (not tight forecasts) — their job is
#: to catch corrupt data such as negative rates or misplaced decimals.
SERIES: dict[str, SeriesConfig] = {
    "UNRATE": SeriesConfig(
        series_id="UNRATE",
        description="Civilian Unemployment Rate (%)",
        frequency="monthly",
        min_value=0.0,
        max_value=50.0,
    ),
    "GDP": SeriesConfig(
        series_id="GDP",
        description="Gross Domestic Product ($B, annual rate)",
        frequency="quarterly",
        min_value=0.0,
        max_value=1_000_000.0,
    ),
    "DGS10": SeriesConfig(
        series_id="DGS10",
        description="10-Year Treasury Constant Maturity Rate (%)",
        frequency="daily",
        min_value=-5.0,
        max_value=25.0,
    ),
}

#: Convenience list of the configured series IDs.
SERIES_IDS: list[str] = list(SERIES.keys())


# ---------------------------------------------------------------------------
# Filesystem paths
# ---------------------------------------------------------------------------

#: Project root (the directory containing ``src/``).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DATA_DIR: Path = DATA_DIR / "raw"
PROCESSED_DATA_DIR: Path = DATA_DIR / "processed"
QA_REPORTS_DIR: Path = PROJECT_ROOT / "qa_reports"
SQL_DIR: Path = PROJECT_ROOT / "sql"

#: Local DuckDB database that holds validated, loaded rows.
DATABASE_PATH: Path = PROCESSED_DATA_DIR / "economic_data.duckdb"

#: Path to the schema DDL used to create the target table.
SCHEMA_SQL_PATH: Path = SQL_DIR / "schema.sql"

#: Name of the table validated rows are loaded into.
TABLE_NAME: str = "economic_data"


def ensure_directories() -> None:
    """Create all output directories if they do not already exist.

    Idempotent — safe to call at the start of every pipeline run.
    """
    for directory in (RAW_DATA_DIR, PROCESSED_DATA_DIR, QA_REPORTS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
