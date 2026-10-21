"""Regression guard for the pytest context-flood fix.

The suite must run in the ``test`` environment so ``app.core.logging.
setup_logging`` keeps ``sqlalchemy.engine`` at WARNING. In ``development``
(the local default) that logger drops to INFO and echoes every
SELECT/SAVEPOINT/ROLLBACK; on a failing run pytest captures and dumps all of
it — thousands of lines that flood the terminal and any agent context window.
``backend/conftest.py`` pins ENVIRONMENT=test to prevent that. These tests
fail loudly if that pin is removed or the logging policy regresses.

Related: backend/conftest.py, app/core/logging.py, Makefile (backend-test),
.claude/hooks/verify-before-stop.sh.
"""

import logging

from app.core.config import settings


def test_suite_runs_in_test_environment():
    # Pinned by backend/conftest.py (setdefault) before app config is imported.
    assert settings.ENVIRONMENT == "test", (
        "Tests must run with ENVIRONMENT=test (see backend/conftest.py). "
        f"Got {settings.ENVIRONMENT!r} — SQL echo would flood test output."
    )


def test_sqlalchemy_sql_echo_is_off_during_tests():
    # The actual flood mechanism: sqlalchemy.engine at INFO echoes every
    # statement. WARNING (or higher) keeps failure output bounded.
    level = logging.getLogger("sqlalchemy.engine").getEffectiveLevel()
    assert level >= logging.WARNING, (
        "sqlalchemy.engine must not emit INFO during tests — that is the "
        f"SQL-echo flood. Effective level is {logging.getLevelName(level)}."
    )
