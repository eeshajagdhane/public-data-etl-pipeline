"""Unit tests for the pure transform logic (raw FRED JSON -> DataFrame)."""

from __future__ import annotations

import pandas as pd
import pytest
from pandas.api import types as ptypes

from src.transform import OUTPUT_COLUMNS, transform_observations


def test_columns_and_order(mock_fred_payload: dict) -> None:
    """Output has exactly the canonical columns in the canonical order."""
    df = transform_observations(mock_fred_payload, "TEST")
    assert list(df.columns) == OUTPUT_COLUMNS


def test_dtypes_are_correct(mock_fred_payload: dict) -> None:
    """date is datetime, value is float, series_id is string/object."""
    df = transform_observations(mock_fred_payload, "TEST")
    assert ptypes.is_datetime64_any_dtype(df["date"])
    assert ptypes.is_float_dtype(df["value"])
    assert ptypes.is_object_dtype(df["series_id"]) or ptypes.is_string_dtype(
        df["series_id"]
    )


def test_missing_value_becomes_nan(mock_fred_payload: dict) -> None:
    """FRED's '.' placeholder is converted to NaN, others parse as floats."""
    df = transform_observations(mock_fred_payload, "TEST")
    assert df["value"].isna().sum() == 1
    march = df.loc[df["date"] == pd.Timestamp("2020-03-01"), "value"]
    assert march.isna().all()
    assert df["value"].max() == pytest.approx(14.8)


def test_series_id_is_stamped(mock_fred_payload: dict) -> None:
    """Every row carries the series_id passed by the caller."""
    df = transform_observations(mock_fred_payload, "UNRATE")
    assert (df["series_id"] == "UNRATE").all()


def test_sorted_by_date() -> None:
    """Rows are returned in ascending date order regardless of input order."""
    payload = {
        "observations": [
            {"date": "2020-03-01", "value": "3.0"},
            {"date": "2020-01-01", "value": "1.0"},
            {"date": "2020-02-01", "value": "2.0"},
        ]
    }
    df = transform_observations(payload, "TEST")
    assert list(df["date"]) == [
        pd.Timestamp("2020-01-01"),
        pd.Timestamp("2020-02-01"),
        pd.Timestamp("2020-03-01"),
    ]


def test_empty_observations_returns_typed_empty_frame() -> None:
    """Zero observations yields an empty frame with the right columns/dtypes."""
    df = transform_observations({"observations": []}, "TEST")
    assert df.empty
    assert list(df.columns) == OUTPUT_COLUMNS
    assert ptypes.is_datetime64_any_dtype(df["date"])
    assert ptypes.is_float_dtype(df["value"])


def test_missing_observations_key_raises() -> None:
    """A payload without 'observations' is a hard error, not a silent pass."""
    with pytest.raises(KeyError):
        transform_observations({"count": 0}, "TEST")
