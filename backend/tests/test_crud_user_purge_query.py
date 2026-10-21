"""Tests for crud_user.get_purge_eligible — drives the hard-purge worker.

Related files:
- app/crud/user.py
- app/services/account_deletion.py (hard-purge will be added)
- docs/account-deletion-plan.md
"""
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud import crud_user
from app.models.session import Session, SessionStatus, SessionType
from app.services.account_deletion import DELETION_GRACE_DAYS
from tests.helpers import create_test_user


def _grace_cutoff(now: datetime) -> datetime:
    return now - timedelta(days=DELETION_GRACE_DAYS)


@pytest.mark.asyncio
class TestGetPurgeEligible:
    async def test_returns_soft_deleted_user_past_grace(
        self, db_session: AsyncSession
    ):
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558500")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 1)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id in {u.id for u in eligible}

    async def test_skips_active_user(self, db_session: AsyncSession):
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558501")

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_skips_user_still_in_grace(self, db_session: AsyncSession):
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558502")
        # Deleted 5 days ago — still within grace.
        user.deleted_at = now - timedelta(days=5)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_skips_user_with_active_session(
        self, db_session: AsyncSession
    ):
        """Per policy: even past grace, hard-purge waits for in-flight
        sessions to terminate so we don't anonymize the owner of a
        live SOS / check-in."""
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558503")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 5)
        session = Session(
            user_id=user.id,
            session_type=SessionType.CHECKIN,
            status=SessionStatus.ACTIVE,
            expected_return_time=now + timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_skips_user_with_missed_session(
        self, db_session: AsyncSession
    ):
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558504")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 5)
        session = Session(
            user_id=user.id,
            session_type=SessionType.CHECKIN,
            status=SessionStatus.MISSED,
            expected_return_time=now - timedelta(hours=1),
        )
        db_session.add(session)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_skips_user_with_alerted_session(
        self, db_session: AsyncSession
    ):
        """ALERTED is the third in-flight status — circle members were
        notified, owner still might mark safe. Purge waits."""
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558506")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 5)
        session = Session(
            user_id=user.id,
            session_type=SessionType.CHECKIN,
            status=SessionStatus.ALERTED,
            expected_return_time=now - timedelta(hours=2),
        )
        db_session.add(session)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_skips_user_with_mixed_terminal_and_active_sessions(
        self, db_session: AsyncSession
    ):
        """A single in-flight session must block purge even if the user
        also has many completed ones — `NOT EXISTS` is the contract,
        not `WHERE all are terminal`."""
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558507")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 5)
        for status in (
            SessionStatus.COMPLETED,
            SessionStatus.COMPLETED,
            SessionStatus.ACTIVE,
        ):
            db_session.add(Session(
                user_id=user.id,
                session_type=SessionType.CHECKIN,
                status=status,
                expected_return_time=now + timedelta(hours=1),
            ))
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id not in {u.id for u in eligible}

    async def test_includes_user_with_only_completed_sessions(
        self, db_session: AsyncSession
    ):
        """Sessions in terminal states (completed, cancelled) don't
        block purge — they're done."""
        now = datetime.now(UTC)
        user = await create_test_user(db_session, phone_number="+14155558505")
        user.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 5)
        for status in (SessionStatus.COMPLETED, SessionStatus.CANCELLED):
            session = Session(
                user_id=user.id,
                session_type=SessionType.CHECKIN,
                status=status,
                expected_return_time=now - timedelta(days=10),
            )
            db_session.add(session)
        await db_session.commit()

        eligible = await crud_user.get_purge_eligible(
            db_session, cutoff=_grace_cutoff(now)
        )

        assert user.id in {u.id for u in eligible}
