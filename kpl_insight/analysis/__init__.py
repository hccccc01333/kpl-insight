"""KPL Series Intelligence V1.

The public entry points are intentionally small:
  load_series(match_id, site_dir) -> Series
  analyze_series(series) -> dict
  render_markdown(report) -> str
"""

from .loaders import SeriesDataError, load_series
from .report import render_markdown
from .series import analyze_series

__all__ = ["SeriesDataError", "load_series", "analyze_series", "render_markdown"]
