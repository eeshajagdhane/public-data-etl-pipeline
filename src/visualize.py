"""Visualization stage: build an HTML dashboard from the loaded database.

Reads the validated data back out of DuckDB and renders one line chart per
series into a single self-contained HTML file (charts embedded as base64 PNGs,
no external assets). This is the human-facing summary of what the pipeline
produced — open it in any browser. It is intentionally read-only: it never
writes to the database.
"""

from __future__ import annotations

import base64
import datetime as dt
import io
import logging
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")  # non-interactive backend; render straight to PNG bytes
import matplotlib.pyplot as plt  # noqa: E402

from src import config  # noqa: E402

logger = logging.getLogger(__name__)


def _utc_timestamp() -> str:
    """Return a filesystem-safe UTC timestamp, e.g. ``20260708T152233Z``."""
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def fetch_series_frame(
    con: duckdb.DuckDBPyConnection, series_id: str
):
    """Fetch one series from the database as a date-sorted DataFrame.

    Args:
        con: An open DuckDB connection.
        series_id: The series to fetch.

    Returns:
        A DataFrame with ``date`` and ``value`` columns ordered by date.
    """
    return con.execute(
        "SELECT date, value FROM economic_data "
        "WHERE series_id = ? ORDER BY date",
        [series_id],
    ).df()


def _render_chart_png(dates, values, title: str, color: str) -> str:
    """Render a single line chart to a base64-encoded PNG data URI.

    Args:
        dates: Sequence of dates for the x-axis.
        values: Sequence of values for the y-axis.
        title: Chart title.
        color: Line color (hex).

    Returns:
        A ``data:image/png;base64,...`` string suitable for an ``<img src>``.
    """
    fig, ax = plt.subplots(figsize=(9, 2.6), dpi=110)
    ax.plot(dates, values, color=color, linewidth=1.1)
    ax.set_title(title, fontsize=11, loc="left")
    ax.margins(x=0)
    ax.grid(True, alpha=0.25, linewidth=0.5)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    fig.tight_layout()

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    plt.close(fig)
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_dashboard(
    db_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    timestamp: str | None = None,
) -> Path:
    """Build a self-contained HTML dashboard from the loaded database.

    Args:
        db_path: Database to read from. Defaults to
            :data:`config.DATABASE_PATH`.
        output_dir: Where to write the HTML. Defaults to
            :data:`config.QA_REPORTS_DIR`.
        timestamp: Optional timestamp string; a UTC one is generated if
            omitted.

    Returns:
        Path to the written HTML file.

    Raises:
        FileNotFoundError: If the database does not exist yet (run the
            pipeline first).
    """
    path = Path(db_path) if db_path is not None else config.DATABASE_PATH
    if not path.exists():
        raise FileNotFoundError(
            f"Database not found at {path}. Run the pipeline first: python -m src"
        )
    out_dir = Path(output_dir) if output_dir is not None else config.QA_REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = timestamp or _utc_timestamp()

    colors = {"UNRATE": "#7F77DD", "GDP": "#D85A30", "DGS10": "#1D9E75"}
    con = duckdb.connect(str(path))
    try:
        cards: list[str] = []
        for series_id, series_cfg in config.SERIES.items():
            df = fetch_series_frame(con, series_id)
            if df.empty:
                continue
            valid = df.dropna(subset=["value"])
            latest = valid.iloc[-1] if not valid.empty else None
            title = f"{series_id} — {series_cfg.description}"
            img = _render_chart_png(
                df["date"], df["value"], title, colors.get(series_id, "#534AB7")
            )
            latest_txt = (
                f"latest {latest['value']:,.2f} on {latest['date']}"
                if latest is not None
                else "no data"
            )
            cards.append(
                f'<div class="card"><img src="{img}" alt="{series_id} chart"/>'
                f'<p class="meta">{len(df):,} rows · {latest_txt}</p></div>'
            )
    finally:
        con.close()

    html = _HTML_TEMPLATE.format(ts=ts, cards="\n".join(cards))
    out_path = out_dir / f"dashboard_{ts}.html"
    out_path.write_text(html, encoding="utf-8")
    logger.info("Wrote dashboard to %s", out_path)
    return out_path


_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Economic data dashboard</title>
<style>
  body {{ font-family: system-ui, -apple-system, sans-serif; margin: 2rem auto;
          max-width: 980px; color: #2C2C2A; padding: 0 1rem; }}
  h1 {{ font-size: 1.4rem; font-weight: 600; }}
  .sub {{ color: #5F5E5A; margin-top: -0.4rem; }}
  .card {{ border: 1px solid #D3D1C7; border-radius: 12px; padding: 1rem;
           margin: 1.2rem 0; }}
  .card img {{ width: 100%; height: auto; }}
  .meta {{ color: #5F5E5A; font-size: 0.9rem; margin: 0.4rem 0 0; }}
  footer {{ color: #888780; font-size: 0.85rem; margin-top: 2rem; }}
</style>
</head>
<body>
<h1>Economic data dashboard</h1>
<p class="sub">Validated FRED series loaded by the ETL pipeline · generated {ts} UTC</p>
{cards}
<footer>Portfolio project — data from FRED (Federal Reserve Economic Data),
served from the pipeline's DuckDB database after passing all quality checks.</footer>
</body>
</html>
"""


def main() -> None:
    """Build the dashboard and print its path."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    path = build_dashboard()
    print(f"\nDashboard written to: {path}")
    print("Open it in your browser, e.g.:  open " + str(path))


if __name__ == "__main__":
    main()
