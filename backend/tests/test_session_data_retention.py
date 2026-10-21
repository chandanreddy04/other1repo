"""Post-session data retention: 7 days, owner-extensible (+7d at a time).

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md E2/3.10):
completing a session stamps purge_after = now + SESSION_DATA_RETENTION_DAYS
(data used to be purged on the very next worker tick), cleanup only touches
sessions past that stamp (NULL = legacy row, still purgeable), and the
owner can push the purge out via PUT /sessions/{id}/retention while the
data still exists.

Related: app/crud/session.py, app/services/session_tasks.py
(cleanup_expired_data), app/api/v1/endpoints/sessions.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.models.session import Session, SessionStatus
from app.models.session_update import SessionUpdate
from app.models.user import User
from app.services.session_tasks import cleanup_expired_data
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _completed_session(
    db: AsyncSession, user: User, *, purge_after: datetime | None
) -> Session:
    session = Session(
        user_id=user.id,
        expected_return_time=datetime.now(UTC) - timedelta(hours=2),
        actual_return_time=datetime.now(UTC) - timedelta(hours=1),
        status=SessionStatus.COMPLETED.value,
        purge_after=purge_after,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


class TestRetentionConfig:
    def test_seven_day_defaults(self):
        assert settings.SESSION_DATA_RETENTION_DAYS == 7
        assert settings.RETENTION_EXTENSION_DAYS == 7


@pytest.mark.asyncio
class TestPurgeAfterStamping:
    async def test_completing_a_session_stamps_retention_window(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597001", full_name="Keeper"
        )
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/complete", headers=_auth(user)
        )
        assert resp.status_code == 200
        await db_session.refresh(session)
        assert session.purge_after is not None
        expected = datetime.now(UTC) + timedelta(
            days=settings.SESSION_DATA_RETENTION_DAYS
        )
        assert abs((session.purge_after - expected).total_seconds()) < 60


@pytest.mark.asyncio
class TestCleanupHonorsRetention:
    async def test_cleanup_skips_sessions_inside_retention(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597002", full_name="Keeper"
        )
        session = await _completed_session(
            db_session, user, purge_after=datetime.now(UTC) + timedelta(days=6)
        )
        db_session.add(
            SessionUpdate(session_id=session.id, latitude=1.0, longitude=2.0)
        )
        await db_session.commit()

        with patch(
            "app.services.session_tasks.BlobStorageService",
            return_value=MagicMock(),
        ):
            await cleanup_expired_data(db_session)

        from sqlalchemy import func, select

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(SessionUpdate)
                .where(SessionUpdate.session_id == session.id)
            )
        ).scalar()
        assert count == 1  # untouched — retention window still open

    async def test_cleanup_purges_past_retention_and_legacy_null(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597003", full_name="Keeper"
        )
        past = await _completed_session(
            db_session, user, purge_after=datetime.now(UTC) - timedelta(minutes=1)
        )
        legacy = await _completed_session(db_session, user, purge_after=None)
        for s in (past, legacy):
            db_session.add(
                SessionUpdate(session_id=s.id, latitude=1.0, longitude=2.0)
            )
        await db_session.commit()

        with patch(
            "app.services.session_tasks.BlobStorageService",
            return_value=MagicMock(),
        ):
            await cleanup_expired_data(db_session)

        from sqlalchemy import func, select

        count = (
            await db_session.execute(
                select(func.count())
                .select_from(SessionUpdate)
                .where(SessionUpdate.session_id.in_([past.id, legacy.id]))
            )
        ).scalar()
        assert count == 0


@pytest.mark.asyncio
class TestRetentionExtension:
    async def test_owner_extends_retention_seven_days(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597004", full_name="Keeper"
        )
        original = datetime.now(UTC) + timedelta(days=3)
        session = await _completed_session(db_session, user, purge_after=original)

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention", headers=_auth(user)
        )
        assert resp.status_code == 200
        new_purge = datetime.fromisoformat(resp.json()["purge_after"])
        expected = original + timedelta(days=settings.RETENTION_EXTENSION_DAYS)
        assert abs((new_purge - expected).total_seconds()) < 5

    async def test_extension_rejected_after_data_deleted(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597005", full_name="Keeper"
        )
        session = await _completed_session(
            db_session, user, purge_after=datetime.now(UTC) - timedelta(days=1)
        )
        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention", headers=_auth(user)
        )
        assert resp.status_code == 400
        assert "already been deleted" in resp.json()["detail"]

    async def test_extension_rejected_while_active(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(
            db_session, phone_number="+14155597006", full_name="Keeper"
        )
        session = Session(
            user_id=user.id,
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention", headers=_auth(user)
        )
        assert resp.status_code == 400

    async def test_extension_owner_only(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155597007", full_name="Owner"
        )
        stranger = await create_test_user(
            db_session, phone_number="+14155597008", full_name="Stranger"
        )
        session = await _completed_session(
            db_session, owner, purge_after=datetime.now(UTC) + timedelta(days=3)
        )
        resp = await client.put(
            f"/api/v1/sessions/{session.id}/retention", headers=_auth(stranger)
        )
        assert resp.status_code in (403, 404)
