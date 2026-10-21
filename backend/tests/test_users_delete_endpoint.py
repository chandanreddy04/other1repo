"""Tests for DELETE /api/v1/users/me.

Related files:
- app/api/v1/endpoints/users.py
- app/services/account_deletion.py
- docs/account-deletion-plan.md
"""
from datetime import datetime
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.services.account_deletion import DELETION_GRACE_DAYS
from tests.helpers import create_test_user


def _auth_headers(user_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user_id)}"}


@pytest.mark.asyncio
class TestDeleteCurrentUser:
    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_soft_deletes_authenticated_user(
        self, _mock_cancel, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155557001")

        response = await client.delete(
            "/api/v1/users/me", headers=_auth_headers(str(user.id))
        )

        assert response.status_code == 200
        body = response.json()
        assert body["soft_deleted"] is True
        assert body["grace_days"] == DELETION_GRACE_DAYS
        # ISO-8601 timestamp — parseable and in the future
        parsed = datetime.fromisoformat(body["scheduled_deletion_at"])
        assert parsed.tzinfo is not None

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_persists_deleted_at_on_user(
        self, _mock_cancel, client: AsyncClient, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155557002")

        await client.delete(
            "/api/v1/users/me", headers=_auth_headers(str(user.id))
        )

        await db_session.refresh(user)
        assert user.deleted_at is not None
        assert user.is_active is False

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_sponsorship_choices_threaded_to_orchestrator(
        self, _mock_cancel, client: AsyncClient, db_session: AsyncSession
    ):
        """The endpoint forwards `sponsorship_choices` verbatim. The
        orchestrator's behavior is covered in test_account_deletion.py;
        here we only verify the request body shape works."""
        user = await create_test_user(db_session, phone_number="+14155557003")

        response = await client.request(
            "DELETE",
            "/api/v1/users/me",
            json={"sponsorship_choices": {"sub_abc": "keep"}},
            headers=_auth_headers(str(user.id)),
        )

        assert response.status_code == 200

    async def test_unauthenticated_rejected(self, client: AsyncClient):
        response = await client.delete("/api/v1/users/me")
        assert response.status_code == 401

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_second_delete_blocked_by_auth(
        self, _mock_cancel, client: AsyncClient, db_session: AsyncSession
    ):
        """After delete, is_active is false — the access token no longer
        authenticates. The user can't re-delete; they'd have to sign in
        again (which goes through the deletion_pending path, added next)."""
        user = await create_test_user(db_session, phone_number="+14155557004")
        headers = _auth_headers(str(user.id))

        first = await client.delete("/api/v1/users/me", headers=headers)
        assert first.status_code == 200

        second = await client.delete("/api/v1/users/me", headers=headers)
        assert second.status_code == 403
