"""Transform stage: parse a raw FRED response into a clean DataFrame.

The core function :func:`transform_observations` is deliberately *pure* — it
takes the decoded FRED payload plus a series ID and returns a tidy DataFrame
with no I/O and no global state. That makes the JSON-to-DataFrame parsing
logic trivial to unit-test with small fixtures.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

#: FRED encodes a missing observation as this single-character string.
FRED_MISSING_VALUE: str = "."

#: The clean, canonical column order produced by the transform.
OUTPUT_COLUMNS: list[str] = ["date", "series_id", "value"]


def transform_observations(payload: dict, series_id: str) -> pd.DataFrame:
    """Parse a raw FRED response into a clean ``date, series_id, value`` frame.

    The returned DataFrame has exactly three columns with correct dtypes:

    * ``date``      — ``datetime64[ns]``
    * ``series_id`` — ``object`` (string), constant for all rows
    * ``value``     — ``float64``; FRED's ``"."`` placeholder becomes ``NaN``

    Args:
        payload: Decoded FRED ``series/observations`` JSON. Must contain an
            ``"observations"`` list of ``{"date", "value", ...}`` records.
        series_id: The FRED series identifier to stamp onto every row. FRED
            does not include this inside each observation, so it is supplied
            by the caller (the code that requested the series).

    Returns:
        A clean DataFrame ordered by date. If there are no observations, an
        empty DataFrame with the correct columns and dtypes is returned.

    Raises:
        KeyError: If ``payload`` has no ``"observations"`` field.
    """
    if "observations" not in payload:
        raise KeyError("payload has no 'observations' field")

    observations = payload["observations"]

    if not observations:
        logger.warning("Series '%s' returned zero observations", series_id)
        return _empty_frame()

    df = pd.DataFrame(observations)

    # Keep only the fields we care about; ignore realtime_start/realtime_end.
    df = df[["date", "value"]].copy()
    df["series_id"] = series_id

    # Type conversion. FRED's "." missing marker is coerced to NaN by turning
    # it into a true NA first, then parsing to float.
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["value"] = df["value"].replace(FRED_MISSING_VALUE, pd.NA)
    df["value"] = pd.to_numeric(df["value"], errors="coerce")

    df = df[OUTPUT_COLUMNS].sort_values("date").reset_index(drop=True)

    n_missing = int(df["value"].isna().sum())
    logger.info(
        "Transformed series '%s': %d rows (%d missing values)",
        series_id,
        len(df),
        n_missing,
    )
    return df


def _empty_frame() -> pd.DataFrame:
    """Return an empty DataFrame with the canonical columns and dtypes."""
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "series_id": pd.Series([], dtype="object"),
            "value": pd.Series([], dtype="float64"),
        }
    )


def transform_raw_file(path: str | Path, series_id: str) -> pd.DataFrame:
    """Load a saved raw JSON file and transform it.

    Thin I/O wrapper around :func:`transform_observations` for use by the
    pipeline; the pure function remains the unit under test.

    Args:
        path: Path to a raw JSON file written by the extract stage.
        series_id: The FRED series identifier the file corresponds to.

    Returns:
        The clean DataFrame for that series.
    """
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return transform_observations(payload, series_id)
