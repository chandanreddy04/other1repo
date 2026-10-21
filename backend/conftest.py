"""Pytest bootstrap for the backend suite (loaded before any app import).

Pins the process into the ``test`` environment — the same value CI exports
(``.github/workflows/ci.yml``) — *before* ``app.core.config`` first reads
``os.getenv("ENVIRONMENT")``.

This is about context hygiene as much as CI parity. ``app.core.logging.
setup_logging`` turns on SQLAlchemy's per-statement SQL echo
(``sqlalchemy.engine`` at INFO) whenever ``ENVIRONMENT == "development"``.
Locally that is the default (``config.py``), so every test emits a stream of
SELECT / SAVEPOINT / ROLLBACK log lines that pytest captures and dumps *in
full* on each failure — thousands of lines that flood the terminal and any
agent context window. Running as ``test`` keeps that logger at WARNING.

``setdefault`` (not a hard set) so an explicit ``ENVIRONMENT=... pytest``
still wins for the rare debug run that wants dev-mode SQL echo.

Related: app/core/logging.py, Makefile (backend-test target),
.claude/hooks/verify-before-stop.sh
"""

import os

os.environ.setdefault("ENVIRONMENT", "test")
# `test` is a non-development environment, so config's reject_default_secret_key
# validator refuses the local dev SECRET_KEY. Supply the same throwaway test key
# CI exports (.github/workflows/ci.yml) so the suite is self-contained and does
# not depend on a shell-exported secret. setdefault: a real export still wins.
os.environ.setdefault("SECRET_KEY", "ci-test-secret-key-not-for-production")
