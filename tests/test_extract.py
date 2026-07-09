"""Unit tests for the extract stage, using a mocked FRED API (no network)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from src import extract
from src.extract import FredAPIError, fetch_series, save_raw_response


class _FakeResponse:
    """Minimal stand-in for requests.Response used to mock FRED calls."""

    def __init__(self, status_code: int, payload: Any) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload) if isinstance(payload, dict) else str(payload)

    def json(self) -> Any:
        if isinstance(self._payload, dict):
            return self._payload
        raise json.JSONDecodeError("no json", "", 0)


def test_missing_key_raises_before_any_request(monkeypatch) -> None:
    """No key -> immediate, clear error (and never touches the network)."""
    # Clear any key loaded from the environment so the test is deterministic.
    monkeypatch.setattr(extract.config, "FRED_API_KEY", None)
    with pytest.raises(FredAPIError, match="FRED_API_KEY is not set"):
        fetch_series("UNRATE", api_key=None)


def test_successful_fetch_returns_payload(monkeypatch) -> None:
    payload = {"observations": [{"date": "2020-01-01", "value": "3.5"}]}
    monkeypatch.setattr(
        extract.requests, "get", lambda *a, **k: _FakeResponse(200, payload)
    )
    result = fetch_series("UNRATE", api_key="x" * 32)
    assert result == payload


def test_rate_limit_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        extract.requests, "get", lambda *a, **k: _FakeResponse(429, {})
    )
    with pytest.raises(FredAPIError, match="Rate limit"):
        fetch_series("UNRATE", api_key="x" * 32)


def test_bad_request_surfaces_fred_message(monkeypatch) -> None:
    body = {"error_code": 400, "error_message": "Bad Request. Unknown series."}
    monkeypatch.setattr(
        extract.requests, "get", lambda *a, **k: _FakeResponse(400, body)
    )
    with pytest.raises(FredAPIError, match="Unknown series"):
        fetch_series("NOPE", api_key="x" * 32)


def test_response_without_observations_raises(monkeypatch) -> None:
    monkeypatch.setattr(
        extract.requests, "get", lambda *a, **k: _FakeResponse(200, {"count": 0})
    )
    with pytest.raises(FredAPIError, match="no 'observations'"):
        fetch_series("UNRATE", api_key="x" * 32)


def test_save_raw_response_writes_file(monkeypatch, tmp_path) -> None:
    """save_raw_response writes valid JSON to the configured raw dir."""
    monkeypatch.setattr(extract.config, "RAW_DATA_DIR", tmp_path)
    payload = {"observations": [{"date": "2020-01-01", "value": "3.5"}]}
    out = save_raw_response("UNRATE", payload)
    assert out.exists()
    assert out.parent == tmp_path
    assert json.loads(out.read_text(encoding="utf-8")) == payload
