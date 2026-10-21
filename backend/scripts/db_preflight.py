"""Fail fast (one line) when the test Postgres is unreachable.

Without this, every test in the suite errors at the `db_session` fixture with a
full `ConnectionRefusedError` traceback — 1500+ tracebacks that flood CI logs
and, worse, the Stop-hook output that gets fed back into the agent's context.
This preflight turns that wall of noise into a single actionable line.

Host/port are read from `tests/conftest.py`'s TEST_DATABASE_URL so they cannot
drift. Related: Makefile `backend-db-preflight` / `backend-test`,
tests/conftest.py, .claude/hooks/verify-before-stop.sh.
"""

from __future__ import annotations

import re
import socket
import sys
from pathlib import Path

_DEFAULT_HOST, _DEFAULT_PORT = "localhost", 5432


def _resolve_host_port() -> tuple[str, int]:
    """Parse host:port out of conftest's TEST_DATABASE_URL; fall back to defaults."""
    conftest = Path(__file__).resolve().parent.parent / "tests" / "conftest.py"
    try:
        text = conftest.read_text()
    except OSError:
        return _DEFAULT_HOST, _DEFAULT_PORT
    # postgresql+asyncpg://user:pass@HOST:PORT/db
    match = re.search(r"@([^:/@\s]+):(\d+)/", text)
    if not match:
        return _DEFAULT_HOST, _DEFAULT_PORT
    return match.group(1), int(match.group(2))


def main() -> int:
    host, port = _resolve_host_port()
    try:
        with socket.create_connection((host, port), timeout=2):
            return 0
    except OSError:
        sys.stderr.write(
            f"\n✗ Test database unreachable at {host}:{port}.\n"
            f"  Start it before running the backend suite:\n"
            f"      docker compose up -d postgres\n"
            f"  (Skipping pytest so 1500+ ConnectionRefused tracebacks don't "
            f"flood the log.)\n\n"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
