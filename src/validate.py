"""Validate stage: data-quality checks and QA report generation.

This is the guardrail between raw ingestion and the analytics layer. A
transformed DataFrame is run through five independent checks — schema, nulls,
date continuity, value range, and duplicates — each returning a structured
pass/fail result with details. The results are then rendered into a timestamped
markdown QA report so failures are auditable rather than silent.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from pandas.api import types as ptypes

from src import config
from src.config import SeriesConfig
from src.transform import OUTPUT_COLUMNS

logger = logging.getLogger(__name__)

#: Maximum plausible gap (in days) between consecutive observations, per
#: frequency. A larger gap flags a likely missing stretch of data. Daily uses
#: 4 so ordinary weekends (a 3-day Fri->Mon gap) pass while real multi-day
#: outages are caught; FRED represents market holidays as null-valued rows, so
#: they surface in the null check rather than here.
FREQUENCY_MAX_GAP_DAYS: dict[str, int] = {
    "daily": 4,
    "monthly": 45,
    "quarterly": 100,
}

#: How many example offending records to include in a check's details.
MAX_EXAMPLES: int = 5


@dataclass
class CheckResult:
    """Outcome of a single data-quality check.

    Attributes:
        name: Human-readable check name.
        passed: Whether the check passed.
        details: One-line explanation of the outcome.
        metrics: Optional structured numbers (counts, percentages) for the
            report.
    """

    name: str
    passed: bool
    details: str
    metrics: dict[str, float] = field(default_factory=dict)


class DataQualityValidator:
    """Run data-quality checks on a single transformed series DataFrame.

    Each ``check_*`` method returns a :class:`CheckResult`; :meth:`run_all`
    executes them in order. The validator never mutates the input DataFrame.
    """

    def __init__(self, df: pd.DataFrame, series_config: SeriesConfig) -> None:
        """Initialise the validator.

        Args:
            df: Transformed DataFrame with ``date, series_id, value`` columns.
            series_config: Metadata for the series (frequency, plausible
                range) driving the continuity and range checks.
        """
        self.df = df
        self.config = series_config
        self.series_id = series_config.series_id

    # ------------------------------------------------------------------ #
    # Individual checks
    # ------------------------------------------------------------------ #

    def check_schema(self) -> CheckResult:
        """Verify the expected columns are present with the expected dtypes."""
        missing = [c for c in OUTPUT_COLUMNS if c not in self.df.columns]
        if missing:
            return CheckResult(
                "schema",
                False,
                f"Missing expected columns: {missing}",
            )

        problems: list[str] = []
        if not ptypes.is_datetime64_any_dtype(self.df["date"]):
            problems.append(f"'date' should be datetime, got {self.df['date'].dtype}")
        if not (
            ptypes.is_object_dtype(self.df["series_id"])
            or ptypes.is_string_dtype(self.df["series_id"])
        ):
            problems.append(
                f"'series_id' should be string, got {self.df['series_id'].dtype}"
            )
        if not ptypes.is_float_dtype(self.df["value"]):
            problems.append(f"'value' should be float, got {self.df['value'].dtype}")

        if problems:
            return CheckResult("schema", False, "; ".join(problems))
        return CheckResult(
            "schema", True, "All expected columns present with correct types."
        )

    def check_nulls(self) -> CheckResult:
        """Fail on nulls in ``date``/``series_id``; report ``value`` null rate.

        Nulls in the key columns break identity and are never acceptable.
        Nulls in ``value`` are expected (FRED missing values) and reported as
        a percentage rather than failed.
        """
        date_nulls = int(self.df["date"].isna().sum())
        id_nulls = int(self.df["series_id"].isna().sum())
        n = len(self.df)
        value_nulls = int(self.df["value"].isna().sum())
        value_null_pct = round(100 * value_nulls / n, 2) if n else 0.0

        metrics = {
            "date_nulls": date_nulls,
            "series_id_nulls": id_nulls,
            "value_nulls": value_nulls,
            "value_null_pct": value_null_pct,
        }

        if date_nulls or id_nulls:
            return CheckResult(
                "null",
                False,
                f"Unexpected nulls in key columns: date={date_nulls}, "
                f"series_id={id_nulls}. value nulls: {value_nulls} "
                f"({value_null_pct}%).",
                metrics,
            )
        return CheckResult(
            "null",
            True,
            f"No nulls in key columns. value nulls: {value_nulls} "
            f"({value_null_pct}%).",
            metrics,
        )

    def check_date_continuity(self) -> CheckResult:
        """Flag gaps between consecutive dates larger than the frequency allows."""
        max_gap = FREQUENCY_MAX_GAP_DAYS.get(self.config.frequency)
        if max_gap is None:
            return CheckResult(
                "date_continuity",
                False,
                f"Unknown frequency '{self.config.frequency}'; cannot check "
                "continuity.",
            )

        dates = self.df["date"].dropna().drop_duplicates().sort_values()
        if len(dates) < 2:
            return CheckResult(
                "date_continuity",
                True,
                f"Too few dates ({len(dates)}) to assess continuity.",
                {"max_gap_days": 0, "gap_count": 0},
            )

        gaps = dates.diff().dt.days.dropna()
        offending = gaps[gaps > max_gap]
        metrics = {
            "max_gap_days": int(gaps.max()),
            "gap_count": int(len(offending)),
            "threshold_days": float(max_gap),
        }

        if len(offending):
            # Report the dates immediately following the largest gaps.
            largest = offending.sort_values(ascending=False).head(MAX_EXAMPLES)
            examples = ", ".join(
                f"{dates.loc[idx].date()} ({int(days)}d gap)"
                for idx, days in largest.items()
            )
            return CheckResult(
                "date_continuity",
                False,
                f"{len(offending)} gap(s) exceed {max_gap}d "
                f"({self.config.frequency}). Largest: {examples}.",
                metrics,
            )
        return CheckResult(
            "date_continuity",
            True,
            f"No gaps exceed {max_gap}d for {self.config.frequency} frequency "
            f"(max observed {metrics['max_gap_days']}d).",
            metrics,
        )

    def check_range(self) -> CheckResult:
        """Flag non-null values outside the configured plausible range."""
        lo, hi = self.config.min_value, self.config.max_value
        values = self.df["value"].dropna()
        out_of_range = values[(values < lo) | (values > hi)]
        metrics = {
            "min_value": float(values.min()) if len(values) else float("nan"),
            "max_value": float(values.max()) if len(values) else float("nan"),
            "out_of_range_count": int(len(out_of_range)),
        }

        if len(out_of_range):
            examples = ", ".join(str(v) for v in out_of_range.head(MAX_EXAMPLES))
            return CheckResult(
                "range",
                False,
                f"{len(out_of_range)} value(s) outside [{lo}, {hi}]. "
                f"Examples: {examples}.",
                metrics,
            )
        return CheckResult(
            "range",
            True,
            f"All values within [{lo}, {hi}] "
            f"(observed {metrics['min_value']}..{metrics['max_value']}).",
            metrics,
        )

    def check_duplicates(self) -> CheckResult:
        """Flag duplicate ``(date, series_id)`` pairs."""
        dup_mask = self.df.duplicated(subset=["date", "series_id"], keep=False)
        dup_count = int(dup_mask.sum())
        metrics = {"duplicate_rows": dup_count}

        if dup_count:
            dup_dates = (
                self.df.loc[dup_mask, "date"]
                .dt.date.astype(str)
                .unique()[:MAX_EXAMPLES]
            )
            return CheckResult(
                "duplicate",
                False,
                f"{dup_count} duplicate (date, series_id) row(s). "
                f"Example dates: {', '.join(dup_dates)}.",
                metrics,
            )
        return CheckResult(
            "duplicate", True, "No duplicate (date, series_id) pairs.", metrics
        )

    # ------------------------------------------------------------------ #
    # Orchestration
    # ------------------------------------------------------------------ #

    def run_all(self) -> list[CheckResult]:
        """Run every check in a fixed order and return the results."""
        results = [
            self.check_schema(),
            self.check_nulls(),
            self.check_date_continuity(),
            self.check_range(),
            self.check_duplicates(),
        ]
        passed = sum(r.passed for r in results)
        logger.info(
            "Validated '%s': %d/%d checks passed (%d rows)",
            self.series_id,
            passed,
            len(results),
            len(self.df),
        )
        return results


@dataclass
class SeriesValidation:
    """Bundle of a series' validation results for reporting.

    Attributes:
        series_id: The FRED series identifier.
        row_count: Number of rows validated.
        results: The list of individual check results.
    """

    series_id: str
    row_count: int
    results: list[CheckResult]

    @property
    def passed(self) -> bool:
        """True only if every check passed."""
        return all(r.passed for r in self.results)


def validate_series(df: pd.DataFrame, series_config: SeriesConfig) -> SeriesValidation:
    """Run all checks for one series and bundle the outcome.

    Args:
        df: Transformed DataFrame for the series.
        series_config: The series' metadata.

    Returns:
        A :class:`SeriesValidation` summarising the run.
    """
    validator = DataQualityValidator(df, series_config)
    return SeriesValidation(
        series_id=series_config.series_id,
        row_count=len(df),
        results=validator.run_all(),
    )


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp, e.g. ``20260708T152233Z``."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def generate_qa_report(
    validations: list[SeriesValidation],
    output_dir: Path | None = None,
    timestamp: str | None = None,
) -> Path:
    """Render validation results to a timestamped markdown QA report.

    Args:
        validations: One :class:`SeriesValidation` per series checked.
        output_dir: Where to write the report. Defaults to
            :data:`config.QA_REPORTS_DIR`.
        timestamp: Optional timestamp string (mainly for tests); a UTC one is
            generated if omitted.

    Returns:
        Path to the written markdown report.
    """
    output_dir = output_dir or config.QA_REPORTS_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or _utc_timestamp()

    overall_pass = all(v.passed for v in validations)
    lines: list[str] = [
        "# Data Quality Report",
        "",
        f"- **Generated (UTC):** {ts}",
        f"- **Series checked:** {len(validations)}",
        f"- **Overall status:** {'✅ PASS' if overall_pass else '❌ FAIL'}",
        "",
        "## Summary",
        "",
        "| Series | Rows | Checks passed | Status |",
        "| --- | ---: | :---: | :---: |",
    ]
    for v in validations:
        n_pass = sum(r.passed for r in v.results)
        status = "✅ PASS" if v.passed else "❌ FAIL"
        lines.append(
            f"| {v.series_id} | {v.row_count:,} | {n_pass}/{len(v.results)} | {status} |"
        )

    for v in validations:
        lines += [
            "",
            f"## {v.series_id}",
            "",
            f"Rows: {v.row_count:,}",
            "",
            "| Check | Result | Details |",
            "| --- | :---: | --- |",
        ]
        for r in v.results:
            mark = "✅" if r.passed else "❌"
            details = r.details.replace("|", "\\|")
            lines.append(f"| {r.name} | {mark} | {details} |")

    report_path = output_dir / f"qa_report_{ts}.md"
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("Wrote QA report to %s", report_path)
    return report_path
