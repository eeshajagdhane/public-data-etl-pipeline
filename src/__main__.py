"""Pipeline entry point: extract -> transform -> validate -> load.

Run with ``python -m src``. Each configured series is pulled, cleaned, and
validated; **only series that pass every data-quality check are loaded** into
the database. A markdown QA report is always written, and a summary (rows
processed, per-series pass/fail, elapsed time) is printed at the end.
"""

from __future__ import annotations

import logging
import time

from src import config
from src.extract import FredAPIError, fetch_series, save_raw_response
from src.load import load_dataframe
from src.transform import transform_observations
from src.validate import SeriesValidation, generate_qa_report, validate_series

logger = logging.getLogger("pipeline")


def _configure_logging() -> None:
    """Set up console logging for a pipeline run."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )


def run_pipeline() -> dict:
    """Run the full ETL pipeline for every configured series.

    For each series: extract from FRED, save the raw response, transform to a
    clean DataFrame, validate it, and — only if all checks pass — load it into
    the database. A QA report covering every series is written at the end.

    Returns:
        A summary dict with keys ``rows_loaded``, ``series_passed``,
        ``series_failed``, ``series_errored``, ``report_path``, and
        ``elapsed_seconds``.
    """
    config.ensure_directories()
    start = time.perf_counter()

    validations: list[SeriesValidation] = []
    rows_loaded = 0
    passed: list[str] = []
    failed: list[str] = []
    errored: list[str] = []

    for series_id, series_cfg in config.SERIES.items():
        try:
            payload = fetch_series(series_id)
            save_raw_response(series_id, payload)
            df = transform_observations(payload, series_id)
        except FredAPIError as exc:
            logger.error("Extract/transform failed for '%s': %s", series_id, exc)
            errored.append(series_id)
            continue

        validation = validate_series(df, series_cfg)
        validations.append(validation)

        # The quality gate: only load data that passed every check.
        if validation.passed:
            rows_loaded += load_dataframe(df)
            passed.append(series_id)
        else:
            failed_checks = [r.name for r in validation.results if not r.passed]
            logger.warning(
                "NOT loading '%s' — failed checks: %s",
                series_id,
                ", ".join(failed_checks),
            )
            failed.append(series_id)

    report_path = generate_qa_report(validations) if validations else None
    elapsed = time.perf_counter() - start

    return {
        "rows_loaded": rows_loaded,
        "series_passed": passed,
        "series_failed": failed,
        "series_errored": errored,
        "report_path": str(report_path) if report_path else None,
        "elapsed_seconds": round(elapsed, 2),
    }


def _print_summary(summary: dict) -> None:
    """Print a human-readable end-of-run summary."""
    print("\n" + "=" * 56)
    print("PIPELINE SUMMARY")
    print("=" * 56)
    print(f"  Rows loaded to DB : {summary['rows_loaded']:,}")
    print(f"  Series passed     : {summary['series_passed'] or '-'}")
    print(f"  Series failed QA  : {summary['series_failed'] or '-'}")
    print(f"  Series errored    : {summary['series_errored'] or '-'}")
    print(f"  QA report         : {summary['report_path'] or '-'}")
    print(f"  Elapsed           : {summary['elapsed_seconds']}s")
    print("=" * 56)


def main() -> None:
    """Configure logging, run the pipeline, and print the summary."""
    _configure_logging()
    summary = run_pipeline()
    _print_summary(summary)


if __name__ == "__main__":
    main()
