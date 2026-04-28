"""Run post-hoc diagnostics on a recorded DuckDB session.

Usage: ``python examples/05_analyze_session.py [path/to/session.duckdb]``
Defaults to ``sessions/example.duckdb``.
"""

from __future__ import annotations

import sys
from pathlib import Path

from kalshi_kit.analysis import compute_session_lag_correlation, diagnose_session


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sessions/example.duckdb")

    print(f"# diagnose_session({path})")
    try:
        bundle = diagnose_session(path)
        print(bundle)
    except FileNotFoundError as exc:
        print(f"session file not found: {exc}")
        return 1
    except Exception as exc:
        print(f"diagnose_session failed: {exc!r}")

    print()
    print(f"# compute_session_lag_correlation({path})")
    try:
        lag_bundle = compute_session_lag_correlation(path)
        print(lag_bundle)
    except FileNotFoundError as exc:
        print(f"session file not found: {exc}")
        return 1
    except Exception as exc:
        print(f"compute_session_lag_correlation failed: {exc!r}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
