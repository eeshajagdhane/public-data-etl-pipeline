"""Unit tests for the data-quality checks — each tested passing and failing."""

from __future__ import annotations

import pandas as pd
import pytest

from src.config import SeriesConfig
from src.validate import (
    DataQualityValidator,
    SeriesValidation,
    generate_qa_report,
    validate_series,
)


# --------------------------------------------------------------------------- #
# Schema check
# --------------------------------------------------------------------------- #


def test_schema_passes_on_clean(clean_df, monthly_config) -> None:
    result = DataQualityValidator(clean_df, monthly_config).check_schema()
    assert result.passed


def test_schema_fails_on_missing_column(clean_df, monthly_config) -> None:
    df = clean_df.drop(columns=["value"])
    result = DataQualityValidator(df, monthly_config).check_schema()
    assert not result.passed


def test_schema_fails_on_wrong_dtype(clean_df, monthly_config) -> None:
    df = clean_df.copy()
    df["value"] = df["value"].astype(str)  # value should be float
    result = DataQualityValidator(df, monthly_config).check_schema()
    assert not result.passed


# --------------------------------------------------------------------------- #
# Null check
# --------------------------------------------------------------------------- #


def test_null_passes_and_reports_value_nulls(clean_df, monthly_config) -> None:
    df = clean_df.copy()
    df.loc[0, "value"] = None  # value nulls are allowed but reported
    result = DataQualityValidator(df, monthly_config).check_nulls()
    assert result.passed
    assert result.metrics["value_nulls"] == 1
    assert result.metrics["value_null_pct"] == pytest.approx(25.0)


def test_null_fails_on_null_key_column(clean_df, monthly_config) -> None:
    df = clean_df.copy()
    df.loc[0, "date"] = pd.NaT  # null in a key column is a failure
    result = DataQualityValidator(df, monthly_config).check_nulls()
    assert not result.passed


# --------------------------------------------------------------------------- #
# Date-continuity check
# --------------------------------------------------------------------------- #


def test_continuity_passes_on_regular_monthly(clean_df, monthly_config) -> None:
    result = DataQualityValidator(clean_df, monthly_config).check_date_continuity()
    assert result.passed


def test_continuity_fails_on_gap(clean_df, monthly_config) -> None:
    # Drop two middle months to open a >45-day gap.
    df = clean_df[clean_df["date"].isin(
        [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-04-01")]
    )].reset_index(drop=True)
    result = DataQualityValidator(df, monthly_config).check_date_continuity()
    assert not result.passed
    assert result.metrics["gap_count"] == 1


# --------------------------------------------------------------------------- #
# Range check
# --------------------------------------------------------------------------- #


def test_range_passes_within_bounds(clean_df, monthly_config) -> None:
    result = DataQualityValidator(clean_df, monthly_config).check_range()
    assert result.passed


def test_range_fails_out_of_bounds(clean_df, monthly_config) -> None:
    df = clean_df.copy()
    df.loc[0, "value"] = 999.0  # config max is 50
    result = DataQualityValidator(df, monthly_config).check_range()
    assert not result.passed
    assert result.metrics["out_of_range_count"] == 1


def test_range_ignores_nan(clean_df, monthly_config) -> None:
    df = clean_df.copy()
    df.loc[0, "value"] = None
    result = DataQualityValidator(df, monthly_config).check_range()
    assert result.passed


# --------------------------------------------------------------------------- #
# Duplicate check
# --------------------------------------------------------------------------- #


def test_duplicates_pass_when_unique(clean_df, monthly_config) -> None:
    result = DataQualityValidator(clean_df, monthly_config).check_duplicates()
    assert result.passed


def test_duplicates_fail_on_repeated_pair(clean_df, monthly_config) -> None:
    df = pd.concat([clean_df, clean_df.iloc[[0]]], ignore_index=True)
    result = DataQualityValidator(df, monthly_config).check_duplicates()
    assert not result.passed
    assert result.metrics["duplicate_rows"] == 2


# --------------------------------------------------------------------------- #
# Orchestration + report
# --------------------------------------------------------------------------- #


def test_validate_series_all_pass(clean_df, monthly_config) -> None:
    validation = validate_series(clean_df, monthly_config)
    assert isinstance(validation, SeriesValidation)
    assert validation.passed
    assert validation.row_count == len(clean_df)


def test_generate_qa_report_writes_file(clean_df, monthly_config, tmp_path) -> None:
    validation = validate_series(clean_df, monthly_config)
    path = generate_qa_report([validation], output_dir=tmp_path, timestamp="TEST_TS")
    assert path.exists()
    content = path.read_text(encoding="utf-8")
    assert "Data Quality Report" in content
    assert "TEST" in content
    assert "PASS" in content
