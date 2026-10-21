"""Regression tests for safety-pipeline production-readiness fixes.

C1: `get_user_contacts` must eager-load `contact_user` so the async alert
    worker doesn't hit MissingGreenlet on a cold object (which silently
    aborted dispatch to that member and everyone after it).
C2: an SOS session must dispatch alerts immediately on creation, not wait
    for the worker's grace-period scan (~2-3 min delay for a panic button).

Related: app/crud/circle_of_trust.py, app/api/v1/endpoints/sessions.py,
         app/services/session_tasks.py.
"""

import pytest
from httpx import AsyncClient
from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.models.alert import Alert, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.session import Session, SessionStatus
from app.models.user import User
from tests.helpers import create_test_user


def _auth(user: User) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _app_contact_member(
    db: AsyncSession, owner: User, phone: str, token: str | None = None
) -> CircleOfTrustMember:
    contact = await create_test_user(db, phone_number=phone, full_name="Buddy")
    if token:
        contact.expo_push_token = token
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname=contact.full_name,
        status=ContactStatus.ACTIVE.value,
    )
    db.add(member)
    await db.commit()
    return member


@pytest.mark.asyncio
class TestC1ContactUserEagerLoaded:
    async def test_get_user_contacts_eager_loads_contact_user(
        self, db_session: AsyncSession
    ):
        owner = await create_test_user(db_session, phone_number="+14155560001")
        await _app_contact_member(
            db_session, owner, "+14155560002", token="ExponentPushToken[x]"
        )

        # Simulate a cold worker: clear the identity map so contact_user is
        # not already resolvable in-memory. Without the selectinload, the
        # access below would raise MissingGreenlet in this async context.
        db_session.expunge_all()

        members = await crud_circle_of_trust.get_user_contacts(
            db_session, user_id=owner.id, status=ContactStatus.ACTIVE
        )
        assert len(members) == 1
        member = members[0]
        # contact_user must already be loaded (not deferred/lazy).
        assert "contact_user" not in inspect(member).unloaded
        # And actually usable without triggering IO.
        assert member.contact_user.expo_push_token == "ExponentPushToken[x]"


@pytest.mark.asyncio
class TestC2SOSImmediateDispatch:
    async def test_sos_dispatches_on_create(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await create_test_user(db_session, phone_number="+14155560010")
        await _app_contact_member(db_session, owner, "+14155560011")

        response = await client.post(
            "/api/v1/sessions",
            headers=_auth(owner),
            json={"session_type": "sos"},
        )
        assert response.status_code == 201
        session_id = response.json()["id"]

        # Inline dispatch should have moved the session out of ACTIVE
        # immediately (claimed -> MISSED, then ALERTED if all reached).
        db_session.expunge_all()
        session = (
            await db_session.execute(select(Session).where(Session.id == session_id))
        ).scalar_one()
        assert session.status != SessionStatus.ACTIVE.value

        # A PANIC alert should exist for the app-account circle member.
        alerts = (
            await db_session.execute(
                select(Alert).where(Alert.session_id == session_id)
            )
        ).scalars().all()
        assert any(a.alert_type == AlertType.PANIC.value for a in alerts)
