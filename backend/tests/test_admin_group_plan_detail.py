"""Admin: group members are shown on the group plan's detail page (via
group_plans_view.related), and the standalone "Group Members" section is gone.

Related: app/web/admin_registry.py (group_plans_view.related).
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.helpers import (
    create_test_group_plan,
    create_test_subscription,
    create_test_user,
)


@pytest.mark.asyncio
class TestAdminGroupPlanDetail:
    async def test_detail_lists_members(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        owner = await create_test_user(
            db_session, phone_number="+14155595001", full_name="Fam Owner"
        )
        sub = await create_test_subscription(db_session, owner)
        plan = await create_test_group_plan(db_session, owner, sub)

        r = await client.get(
            f"/admin/group-plans/{plan.id}", cookies=admin_cookies
        )
        assert r.status_code == 200
        body = r.text
        assert "Group members" in body
        assert "Fam Owner" in body  # the owner is member #1

    async def test_standalone_group_members_section_removed(
        self, client: AsyncClient, admin_cookies: dict
    ):
        r = await client.get("/admin/group-plan-members", cookies=admin_cookies)
        assert r.status_code == 404
        # A member-detail route is gone too.
        r2 = await client.get(
            f"/admin/group-plan-members/{uuid.uuid4()}", cookies=admin_cookies
        )
        assert r2.status_code == 404
