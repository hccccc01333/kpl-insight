"""All generated data lives under KPL_DATA_ROOT (default: working directory)."""
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("KPL_DATA_ROOT", str(Path.cwd()))).expanduser().resolve()
