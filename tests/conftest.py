"""Shared pytest fixtures: small, hand-written mock data for the unit tests.

Keeping fixtures here (rather than in each test module) lets the transform and
validate tests reuse the same mock FRED payload and DataFrames.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import SeriesConfig


@pytest.fixture
def mock_fred_payload() -> dict:
    """A minimal FRED ``series/observations`` response.

    Mirrors the real shape: an ``observations`` list of records with ``date``
    and ``value`` strings, including one ``"."`` missing-value placeholder.
    """
    return {
        "realtime_start": "2026-07-08",
        "realtime_end": "2026-07-08",
        "observation_start": "2020-01-01",
        "observation_end": "2020-04-01",
        "units": "lin",
        "count": 4,
        "observations": [
            {"date": "2020-01-01", "value": "3.5"},
            {"date": "2020-02-01", "value": "3.8"},
            {"date": "2020-03-01", "value": "."},  # missing -> NaN
            {"date": "2020-04-01", "value": "14.8"},
        ],
    }


@pytest.fixture
def monthly_config() -> SeriesConfig:
    """A monthly series config with a plausible range of [0, 50]."""
    return SeriesConfig(
        series_id="TEST",
        description="Test monthly series",
        frequency="monthly",
        min_value=0.0,
        max_value=50.0,
    )


@pytest.fixture
def clean_df() -> pd.DataFrame:
    """A well-formed monthly DataFrame that should pass every check."""
    return pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2020-01-01", "2020-02-01", "2020-03-01", "2020-04-01"]
            ),
            "series_id": ["TEST"] * 4,
            "value": [3.5, 3.8, 4.0, 14.8],
        }
    )
