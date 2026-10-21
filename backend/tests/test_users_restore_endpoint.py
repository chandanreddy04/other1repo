"""Tests for POST /api/v1/users/me/restore.

Related files:
- app/api/v1/endpoints/users.py
- app/api/v1/deps/auth.py (get_current_user_allow_soft_deleted)
- app/services/account_deletion.py
"""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.services.account_deletion import DELETION_GRACE_DAYS
from tests.helpers import create_test_user


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.mark.asyncio
class TestRestoreCurrentUser:
    async def test_clears_deleted_at_for_soft_deleted_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155556001")
        user.deleted_at = datetime.now(UTC)
        user.is_active = False
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/me/restore", headers=_auth_headers(str(user.id))
        )

        assert response.status_code == 200
        await db_session.refresh(user)
        assert user.deleted_at is None
        assert user.is_active is True

    async def test_idempotent_on_active_user(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """A user who never deleted should still get a 200 — restore is
        idempotent. Prevents bad client retries from causing UX errors."""
        user = await create_test_user(db_session, phone_number="+14155556002")

        response = await client.post(
            "/api/v1/users/me/restore", headers=_auth_headers(str(user.id))
        )

        assert response.status_code == 200

    async def test_unauthenticated_rejected(self, client: AsyncClient):
        response = await client.post("/api/v1/users/me/restore")
        assert response.status_code == 401

    async def test_past_grace_user_returns_410_gone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Once the 30-day grace expires, restore should not clobber a
        row that's destined for hard-purge. Mobile reads 410 Gone as
        'go through new-account signup'."""
        user = await create_test_user(db_session, phone_number="+14155556004")
        user.deleted_at = datetime.now(UTC) - timedelta(
            days=DELETION_GRACE_DAYS + 1
        )
        user.is_active = False
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/me/restore", headers=_auth_headers(str(user.id))
        )

        assert response.status_code == 410
        await db_session.refresh(user)
        # State untouched.
        assert user.deleted_at is not None
        assert user.is_active is False

    async def test_admin_disabled_user_rejected(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """An inactive user with deleted_at IS NULL is admin-disabled,
        not soft-deleted — they should not be able to self-restore."""
        user = await create_test_user(db_session, phone_number="+14155556003")
        user.is_active = False  # but deleted_at stays None
        await db_session.commit()

        response = await client.post(
            "/api/v1/users/me/restore", headers=_auth_headers(str(user.id))
        )

        assert response.status_code == 403
