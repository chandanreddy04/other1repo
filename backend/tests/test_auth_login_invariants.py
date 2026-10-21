"""Per-login account invariants enforced by verify-otp.

- Designated admin phone numbers always get is_admin (they must never lose it).
- circle_invite_code / share_code are backfilled if missing — without a
  circle_invite_code the shared /c/{code} invite link is dead ("Invalid circle
  invite code").

Related: app/api/v1/endpoints/auth.py, app/core/config.py
"""
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from tests.helpers import create_test_user


async def _verify(client: AsyncClient, phone: str):
    with patch(
        "app.api.v1.endpoints.auth.otp_service.verify_otp"
    ) as mock_verify, patch(
        "app.api.v1.endpoints.auth.format_to_e164"
    ) as mock_format:
        mock_verify.return_value = (True, "Verified")
        mock_format.return_value = phone
        return await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone_number": phone, "otp_code": "123456"},
        )


@pytest.mark.asyncio
class TestLoginInvariants:
    async def test_admin_phone_becomes_admin_on_login(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        phone = settings.ADMIN_PHONE_NUMBERS[0]
        user = await create_test_user(db_session, phone_number=phone)
        assert user.is_admin is False

        resp = await _verify(client, phone)
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.is_admin is True

    async def test_non_admin_phone_stays_non_admin(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        phone = "+14155559012"
        user = await create_test_user(db_session, phone_number=phone)

        resp = await _verify(client, phone)
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.is_admin is False

    async def test_login_backfills_missing_invite_codes(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        phone = "+14155559013"
        user = await create_test_user(db_session, phone_number=phone)
        # New test users start with no codes — exactly the "old account" state
        # that produced the dead invite link.
        assert user.circle_invite_code is None
        assert user.share_code is None

        resp = await _verify(client, phone)
        assert resp.status_code == 200

        await db_session.refresh(user)
        assert user.circle_invite_code is not None
        assert len(user.circle_invite_code) == 8
        assert user.share_code is not None
