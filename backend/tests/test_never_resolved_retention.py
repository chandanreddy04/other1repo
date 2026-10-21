"""Never-resolved sessions are deliberately NOT auto-purged (owner decision
2026-07-19): a session stuck MISSED/ALERTED may be the missing-person case
this app exists for — its location trail and photos are potential evidence,
and the one person who could extend retention is the person who is missing.
Disposal is a human decision (admin actions). This pin prevents a future
"optimization" from silently destroying that data on a timer.

Related: app/services/session_tasks.py::cleanup_expired_data,
tests/test_admin_session_actions.py (the human disposal path).
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.services.session_tasks import cleanup_expired_data
from tests.helpers import create_test_user

_PHONE = iter(f"+141555920{n:02d}" for n in range(1, 99))


async def _old_session_with_data(
    db: AsyncSession, *, status: str, days_old: int = 30
) -> Session:
    owner = await create_test_user(
        db, phone_number=next(_PHONE), full_name="Olive Owner"
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(days=days_old),
        status=status,
        # NULL purge_after would make a TERMINAL session instantly purgeable;
        # non-terminal sessions must survive regardless.
        purge_after=None,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    db.add(
        SessionUpdate(
            session_id=session.id,
            latitude=40.7,
            longitude=-73.9,
            battery_level=0.5,
            recorded_at=datetime.now(UTC) - timedelta(days=days_old),
        )
    )
    await db.commit()
    return session


@pytest.mark.asyncio
class TestNeverResolvedRetention:
    @pytest.mark.parametrize(
        "status", [SessionStatus.MISSED.value, SessionStatus.ALERTED.value]
    )
    async def test_stuck_sessions_survive_cleanup(
        self, db_session: AsyncSession, status: str
    ):
        session = await _old_session_with_data(db_session, status=status)

        with patch(
            "app.services.session_tasks.BlobStorageService",
            return_value=MagicMock(),
        ):
            await cleanup_expired_data(db_session)

        rows = (
            (
                await db_session.execute(
                    select(SessionUpdate).where(
                        SessionUpdate.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows, "never-resolved session data must NOT be auto-purged"

    async def test_terminal_session_is_still_purged(
        self, db_session: AsyncSession
    ):
        """The carve-out is ONLY for never-resolved sessions — the normal
        retention path keeps working for completed ones."""
        session = await _old_session_with_data(
            db_session, status=SessionStatus.COMPLETED.value
        )

        mock_blob = MagicMock()

        async def _ok(_key):
            return True

        mock_blob.delete_file = _ok
        with patch(
            "app.services.session_tasks.BlobStorageService",
            return_value=mock_blob,
        ):
            await cleanup_expired_data(db_session)

        rows = (
            (
                await db_session.execute(
                    select(SessionUpdate).where(
                        SessionUpdate.session_id == session.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows == []
