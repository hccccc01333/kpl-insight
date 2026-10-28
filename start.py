"""Default source-checkout entry point; no dependency installation required."""
from kpl_insight.web import main

if __name__ == "__main__":
    raise SystemExit(main())
