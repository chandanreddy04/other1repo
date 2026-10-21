"""Regression for security #5: refresh tokens can be revoked via token_version.

A refresh token embeds the user's token_version at issue time. Bumping
users.token_version (e.g. on account soft-delete / a future log-out-all)
invalidates every outstanding refresh token without disabling the account.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_refresh_token
from app.services.account_deletion import soft_delete_user
from tests.helpers import create_test_user

REFRESH = "/api/v1/auth/refresh"


@pytest.mark.asyncio
async def test_token_version_bump_revokes_refresh_token(
    client: AsyncClient, db_session: AsyncSession
):
    user = await create_test_user(db_session, phone_number="+14155567001")

    token = create_refresh_token(str(user.id), token_version=user.token_version)

    # Valid initially.
    ok = await client.post(REFRESH, json={"refresh_token": token})
    assert ok.status_code == 200

    # Bump the user's token_version — the old token is now stale.
    user.token_version += 1
    await db_session.commit()

    revoked = await client.post(REFRESH, json={"refresh_token": token})
    assert revoked.status_code == 401


@pytest.mark.asyncio
async def test_soft_delete_revokes_refresh_tokens(
    client: AsyncClient, db_session: AsyncSession
):
    user = await create_test_user(db_session, phone_number="+14155567002")
    token = create_refresh_token(str(user.id), token_version=user.token_version)

    await soft_delete_user(db_session, user)

    resp = await client.post(REFRESH, json={"refresh_token": token})
    # Rejected (inactive + bumped token_version).
    assert resp.status_code in (401, 403)
