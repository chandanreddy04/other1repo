"""H1 regression: refresh tokens must not authenticate as access tokens.

create_access_token stamps type=access; the access-path deps reject any token
whose type isn't "access" (so a long-lived refresh token can't be used as a
bearer access token). /refresh still accepts refresh tokens (covered elsewhere).
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, create_refresh_token
from tests.helpers import create_test_user


@pytest.mark.asyncio
async def test_refresh_token_rejected_as_access_token(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_test_user(
        db_session, phone_number="+14155572000", full_name="Jwt User"
    )
    refresh = create_refresh_token(str(user.id))
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {refresh}"}
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_access_token_accepted(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await create_test_user(
        db_session, phone_number="+14155572001", full_name="Jwt User2"
    )
    access = create_access_token(str(user.id))
    resp = await client.get(
        "/api/v1/users/me", headers={"Authorization": f"Bearer {access}"}
    )
    assert resp.status_code == 200
