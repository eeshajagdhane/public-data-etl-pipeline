"""Load stage: upsert validated rows into a DuckDB database.

The load is idempotent: re-running the pipeline updates existing
``(date, series_id)`` rows in place rather than creating duplicates, thanks to
the primary key defined in ``sql/schema.sql`` and an ``INSERT ... ON CONFLICT``
upsert. This means the pipeline can be run on a schedule without the table ever
accumulating duplicate observations.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd

from src import config
from src.transform import OUTPUT_COLUMNS

logger = logging.getLogger(__name__)


def get_connection(db_path: str | Path | None = None) -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) a DuckDB connection.

    Args:
        db_path: Path to the database file. Defaults to
            :data:`config.DATABASE_PATH`. The parent directory is created if
            it does not exist.

    Returns:
        An open DuckDB connection.
    """
    path = Path(db_path) if db_path is not None else config.DATABASE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def create_table_if_not_exists(
    con: duckdb.DuckDBPyConnection, schema_path: str | Path | None = None
) -> None:
    """Create the target table by executing the schema DDL.

    The DDL uses ``CREATE TABLE IF NOT EXISTS`` so this is safe to call on
    every run.

    Args:
        con: An open DuckDB connection.
        schema_path: Path to the schema SQL file. Defaults to
            :data:`config.SCHEMA_SQL_PATH`.
    """
    path = Path(schema_path) if schema_path is not None else config.SCHEMA_SQL_PATH
    ddl = path.read_text(encoding="utf-8")
    con.execute(ddl)
    logger.debug("Ensured table exists using %s", path)


def upsert_dataframe(
    con: duckdb.DuckDBPyConnection,
    df: pd.DataFrame,
    table_name: str | None = None,
) -> int:
    """Upsert a DataFrame into the target table keyed on ``(date, series_id)``.

    Existing rows with a matching key have their ``value`` updated; new rows
    are inserted. The input DataFrame is not modified.

    Args:
        con: An open DuckDB connection with the target table present.
        df: Clean DataFrame with ``date, series_id, value`` columns.
        table_name: Target table. Defaults to :data:`config.TABLE_NAME`.

    Returns:
        The number of rows submitted for upsert (``len(df)``).

    Raises:
        ValueError: If ``df`` is missing any of the expected columns.
    """
    table = table_name or config.TABLE_NAME
    missing = [c for c in OUTPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"DataFrame is missing expected columns: {missing}")

    if df.empty:
        logger.info("No rows to load into '%s'.", table)
        return 0

    # Register the frame so it can be referenced from SQL, then upsert. The
    # ON CONFLICT clause relies on the primary key from schema.sql.
    ordered = df[OUTPUT_COLUMNS]
    con.register("incoming", ordered)
    try:
        con.execute(
            f"""
            INSERT INTO {table} (date, series_id, value)
            SELECT date, series_id, value FROM incoming
            ON CONFLICT (date, series_id) DO UPDATE SET value = excluded.value
            """
        )
    finally:
        con.unregister("incoming")

    logger.info("Upserted %d rows into '%s'.", len(ordered), table)
    return len(ordered)


def load_dataframe(
    df: pd.DataFrame,
    db_path: str | Path | None = None,
    schema_path: str | Path | None = None,
    table_name: str | None = None,
) -> int:
    """Create the table if needed and upsert a DataFrame in one call.

    High-level entry point used by the pipeline; opens its own connection and
    closes it when done.

    Args:
        df: Clean, validated DataFrame to load.
        db_path: Database path override.
        schema_path: Schema DDL path override.
        table_name: Target table name override.

    Returns:
        The number of rows upserted.
    """
    con = get_connection(db_path)
    try:
        create_table_if_not_exists(con, schema_path)
        return upsert_dataframe(con, df, table_name)
    finally:
        con.close()
