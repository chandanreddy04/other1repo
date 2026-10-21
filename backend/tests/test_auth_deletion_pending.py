"""Tests for verify-otp's deletion_pending response.

When a soft-deleted user signs back in during the 30-day grace window,
verify-otp returns deletion_pending=true plus tokens that work only
against the restore endpoint. This is what drives the Welcome Back
screen on mobile.

Related files:
- app/api/v1/endpoints/auth.py
- app/api/v1/endpoints/users.py (restore endpoint consumes the tokens)
- docs/account-deletion-plan.md
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.account_deletion import DELETION_GRACE_DAYS
from tests.helpers import create_test_user


@pytest.mark.asyncio
class TestVerifyOtpDeletionPending:
    async def test_soft_deleted_user_gets_deletion_pending_flag(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        phone = "+14155555001"
        user = await create_test_user(db_session, phone_number=phone)
        deleted_at = datetime.now(UTC)
        user.deleted_at = deleted_at
        user.is_active = False
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.auth.otp_service.verify_otp"
        ) as mock_verify, patch(
            "app.api.v1.endpoints.auth.format_to_e164"
        ) as mock_format:
            mock_verify.return_value = (True, "Verified")
            mock_format.return_value = phone

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": phone, "otp_code": "123456"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["deletion_pending"] is True
        assert body["is_new_user"] is False
        assert body["user"] is None  # full user profile withheld
        assert body["access_token"]
        assert body["refresh_token"]
        # scheduled_deletion_at == deleted_at + grace
        parsed = datetime.fromisoformat(body["scheduled_deletion_at"])
        expected = deleted_at + timedelta(days=DELETION_GRACE_DAYS)
        assert abs((parsed - expected).total_seconds()) < 1

    async def test_active_user_signin_unchanged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """The deletion_pending branch must not affect normal sign-in for
        un-deleted users — they get the existing response shape."""
        phone = "+14155555002"
        await create_test_user(db_session, phone_number=phone)

        with patch(
            "app.api.v1.endpoints.auth.otp_service.verify_otp"
        ) as mock_verify, patch(
            "app.api.v1.endpoints.auth.format_to_e164"
        ) as mock_format:
            mock_verify.return_value = (True, "Verified")
            mock_format.return_value = phone

            response = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": phone, "otp_code": "123456"},
            )

        body = response.json()
        assert body["deletion_pending"] is False
        assert body["scheduled_deletion_at"] is None

    async def test_token_from_deletion_pending_only_works_for_restore(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """End-to-end: a soft-deleted user signs in, receives a token,
        uses it to call /restore — and after that, the same token works
        for normal endpoints."""
        phone = "+14155555003"
        user = await create_test_user(db_session, phone_number=phone)
        user.deleted_at = datetime.now(UTC)
        user.is_active = False
        await db_session.commit()

        with patch(
            "app.api.v1.endpoints.auth.otp_service.verify_otp"
        ) as mock_verify, patch(
            "app.api.v1.endpoints.auth.format_to_e164"
        ) as mock_format:
            mock_verify.return_value = (True, "Verified")
            mock_format.return_value = phone

            sign_in = await client.post(
                "/api/v1/auth/verify-otp",
                json={"phone_number": phone, "otp_code": "123456"},
            )

        token = sign_in.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Before restore: /me 403s
        me_before = await client.get("/api/v1/users/me", headers=headers)
        assert me_before.status_code == 403

        # Restore succeeds
        restore = await client.post(
            "/api/v1/users/me/restore", headers=headers
        )
        assert restore.status_code == 200

        # After restore: same token works for /me
        me_after = await client.get("/api/v1/users/me", headers=headers)
        assert me_after.status_code == 200
