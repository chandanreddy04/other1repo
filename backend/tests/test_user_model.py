"""Tests for the User model — focused on the soft-delete column.

Related files:
- app/models/user.py (model definition)
- alembic/versions/20260608_0132-*_add_users_deleted_at_for_soft_delete_.py
- docs/account-deletion-plan.md (state machine)
"""
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestUserDeletedAt:
    async def test_new_user_deleted_at_defaults_to_none(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558001")
        assert user.deleted_at is None

    async def test_deleted_at_persists_when_set(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155558002")
        marker = datetime.now(UTC)
        user.deleted_at = marker
        await db_session.commit()
        await db_session.refresh(user)

        fetched = (
            await db_session.execute(select(User).where(User.id == user.id))
        ).scalar_one()
        assert fetched.deleted_at is not None
        # Round-trip preserves the timestamp (tz-aware).
        assert fetched.deleted_at.tzinfo is not None
        assert abs((fetched.deleted_at - marker).total_seconds()) < 1

    async def test_deleted_at_is_queryable_for_purge_scan(
        self, db_session: AsyncSession
    ):
        """The hard-purge worker filters by deleted_at IS NOT NULL — that
        query must return only soft-deleted rows."""
        live = await create_test_user(db_session, phone_number="+14155558003")
        soft = await create_test_user(db_session, phone_number="+14155558004")
        soft.deleted_at = datetime.now(UTC)
        await db_session.commit()

        scheduled = (
            await db_session.execute(
                select(User).where(User.deleted_at.is_not(None))
            )
        ).scalars().all()
        scheduled_ids = {u.id for u in scheduled}
        assert soft.id in scheduled_ids
        assert live.id not in scheduled_ids
