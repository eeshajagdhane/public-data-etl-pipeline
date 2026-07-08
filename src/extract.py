"""Extract stage: pull raw observations from the FRED API and save them.

Each series is fetched from the FRED ``series/observations`` endpoint and the
raw JSON response is written verbatim to ``data/raw/`` with a timestamp. Saving
the untouched response keeps extraction and parsing separate: raw pulls are a
reproducible audit trail, and the transform stage can be re-run against them
without hitting the API again.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from pathlib import Path

import requests

from src import config

logger = logging.getLogger(__name__)

#: Network timeout (seconds) for a single FRED request.
REQUEST_TIMEOUT: int = 30


class FredAPIError(RuntimeError):
    """Raised when the FRED API cannot be queried or returns an error."""


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp, e.g. ``20260708T152233Z``."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fetch_series(series_id: str, api_key: str | None = None) -> dict:
    """Fetch a single FRED series and return the parsed JSON response.

    Args:
        series_id: FRED series identifier (e.g. ``"UNRATE"``).
        api_key: FRED API key. Defaults to :data:`config.FRED_API_KEY`.

    Returns:
        The decoded JSON response as a dictionary.

    Raises:
        FredAPIError: If the API key is missing, the request fails or times
            out, the series is not found, the key is invalid, or the rate
            limit is exceeded. The message identifies the specific cause.
    """
    key = api_key or config.FRED_API_KEY
    if not key:
        raise FredAPIError(
            "FRED_API_KEY is not set. Copy .env.example to .env and add your "
            "key (get one free at https://fredaccount.stlouisfed.org/apikeys)."
        )

    params = {
        "series_id": series_id,
        "api_key": key,
        "file_type": "json",
    }

    logger.info("Fetching FRED series '%s'", series_id)
    try:
        response = requests.get(
            config.FRED_BASE_URL, params=params, timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.Timeout as exc:
        raise FredAPIError(
            f"Request for series '{series_id}' timed out after "
            f"{REQUEST_TIMEOUT}s."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise FredAPIError(
            f"Network error fetching series '{series_id}': {exc}"
        ) from exc

    # FRED returns 400 with an {"error_code", "error_message"} body for most
    # problems (bad key, unknown series, etc.) and 429 when rate-limited.
    if response.status_code == 429:
        raise FredAPIError(
            f"Rate limit exceeded while fetching '{series_id}'. Wait a minute "
            "and retry, or reduce request frequency."
        )
    if response.status_code != 200:
        detail = _extract_error_message(response)
        raise FredAPIError(
            f"FRED API returned HTTP {response.status_code} for series "
            f"'{series_id}': {detail}"
        )

    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        raise FredAPIError(
            f"FRED API returned non-JSON response for series '{series_id}'."
        ) from exc

    if "observations" not in payload:
        raise FredAPIError(
            f"FRED response for series '{series_id}' contained no "
            f"'observations' field: {payload}"
        )

    logger.info(
        "Fetched %d observations for series '%s'",
        len(payload["observations"]),
        series_id,
    )
    return payload


def _extract_error_message(response: requests.Response) -> str:
    """Pull FRED's error_message out of a non-200 response, if present."""
    try:
        body = response.json()
        return str(body.get("error_message", body))
    except json.JSONDecodeError:
        return response.text[:200]


def save_raw_response(series_id: str, payload: dict) -> Path:
    """Write a raw FRED response to ``data/raw/{series_id}_{timestamp}.json``.

    Args:
        series_id: FRED series identifier, used in the filename.
        payload: The decoded JSON response to persist.

    Returns:
        The path the raw JSON was written to.
    """
    config.ensure_directories()
    filename = f"{series_id}_{_utc_timestamp()}.json"
    out_path = config.RAW_DATA_DIR / filename
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    logger.info("Saved raw response to %s", out_path)
    return out_path


def extract_series(series_id: str, api_key: str | None = None) -> Path:
    """Fetch a series and persist its raw response in one step.

    Args:
        series_id: FRED series identifier.
        api_key: Optional API key override.

    Returns:
        Path to the saved raw JSON file.
    """
    payload = fetch_series(series_id, api_key=api_key)
    return save_raw_response(series_id, payload)


def main() -> list[Path]:
    """Extract every configured series, continuing past individual failures.

    Returns:
        Paths of the raw files successfully written. A series that fails is
        logged as an error and skipped, so one bad series does not abort the
        whole extract run.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    saved: list[Path] = []
    for series_id in config.SERIES_IDS:
        try:
            saved.append(extract_series(series_id))
        except FredAPIError as exc:
            logger.error("Skipping series '%s': %s", series_id, exc)
    logger.info("Extract complete: %d/%d series saved", len(saved), len(config.SERIES_IDS))
    return saved


if __name__ == "__main__":
    main()
