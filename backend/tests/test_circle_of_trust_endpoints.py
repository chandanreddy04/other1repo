"""
Comprehensive tests for Circle of Trust endpoints.

Covers all branches in app/api/v1/endpoints/circle_of_trust.py:
  - GET /circle/members: enrichment loop (can_nudge, app-user details, SMS fields)
  - POST /circle/members: all add-contact branches
  - DELETE /circle/members/{member_id}: success, 404, 403
  - GET/PUT /circle/settings

The GET /invitations, POST /invitations/{inviter_id}/accept and
POST /invitations/{inviter_id}/decline mobile API routes (app/api/v1/
endpoints/invitations.py) were removed 2026-09-22 (no in-app caller —
Circle members use mobile web only). The invariants they covered now live
in tests/test_circle_member_services.py: accept (self-accept rejection,
wrong-phone rejection, re-accept idempotency) at the service level in
TestAcceptCircleInvite. The web routes are covered in
tests/test_web_circles.py: decline (soft REMOVED, impostor and
already-ACTIVE no-ops) on POST /circles/{invite_code}/decline in
TestCircleDecline, and the accept's referral offer in TestCircleAccept.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud import crud_circle_of_trust, crud_user
from app.models.circle_of_trust import CircleOfTrustMember as CircleOfTrustMemberModel
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from app.schemas.user import UserCreate

BASE = "/api/v1/circle/members"
SETTINGS_BASE = "/api/v1/circle/settings"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, phone: str, name: str):
    """Create a user with full_name set (required by get_current_user_with_profile)."""
    user = await crud_user.create(
        db, obj_in=UserCreate(phone_number=phone, full_name=name)
    )
    await db.commit()
    await db.refresh(user)
    return user


def _auth(user) -> dict:
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


async def _add_non_app(
    db: AsyncSession,
    user_id: uuid.UUID,
    name: str,
    phone: str,
    phone_contact_id: str | None = None,
) -> CircleOfTrustMemberModel:
    m = await crud_circle_of_trust.create_by_phone(
        db,
        user_id=user_id,
        obj_in=CircleOfTrustMemberCreate(
            nickname=name,
            contact_phone_number=phone,
            phone_contact_id=phone_contact_id,
        ),
    )
    await db.commit()
    await db.refresh(m)
    return m


async def _add_app_contact(
    db: AsyncSession, owner_id: uuid.UUID, contact_user_id: uuid.UUID
) -> CircleOfTrustMemberModel:
    contact = await crud_user.get(db, id=contact_user_id)
    m = CircleOfTrustMemberModel(
        user_id=owner_id,
        contact_phone_number_id=contact.phone_number_id,
        invited_at=datetime.now(UTC),
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


# ===========================================================================
# 1. GET /circle/members — enrichment
# ===========================================================================


@pytest.mark.asyncio
class TestGetTrustedContacts:
    """Cover enrichment loop: can_nudge logic, app-user detail injection."""

    async def test_returns_non_app_contact_with_can_nudge_true(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550001", "GetList1")
        await _add_non_app(db_session, user.id, "Alice", "+14085550002")

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 1
        assert items[0]["can_nudge"] is True
        assert items[0]["nickname"] == "Alice"
        assert items[0]["is_app_user"] is False
        assert items[0].get("contact_full_name") is None

    async def test_can_nudge_false_within_24h(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550003", "GetList2")
        m = await _add_non_app(db_session, user.id, "Bob", "+14085550004")
        m.last_nudged_at = datetime.now(UTC) - timedelta(hours=2)
        db_session.add(m)
        await db_session.commit()

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        assert r.json()[0]["can_nudge"] is False
        assert r.json()[0]["last_nudged_at"] is not None

    async def test_can_nudge_true_after_24h(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550005", "GetList3")
        m = await _add_non_app(db_session, user.id, "Carol", "+14085550006")
        m.last_nudged_at = datetime.now(UTC) - timedelta(hours=25)
        db_session.add(m)
        await db_session.commit()

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        assert r.json()[0]["can_nudge"] is True

    async def test_active_contact_cannot_be_nudged(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550007", "GetList4")
        cu = await _make_user(db_session, "+14085550008", "ActivePal")
        m = await _add_app_contact(db_session, user.id, cu.id)
        await crud_circle_of_trust.accept_invitation(db_session, contact=m)
        await db_session.commit()

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()
        assert data[0]["can_nudge"] is False
        assert data[0]["status"] == "active"

    async def test_app_user_enriched_with_name_and_phone(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550009", "GetList5")
        cu = await _make_user(db_session, "+14085550010", "DetailedPal")
        await _add_app_contact(db_session, user.id, cu.id)

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()
        assert data[0]["contact_full_name"] == "DetailedPal"
        assert data[0]["contact_phone"] == "+14085550010"
        assert data[0]["is_app_user"] is True

    async def test_mixed_contacts_list(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550011", "GetList6")
        cu = await _make_user(db_session, "+14085550012", "AppBuddy")
        await _add_app_contact(db_session, user.id, cu.id)
        await _add_non_app(db_session, user.id, "NonAppBuddy", "+14085550013")

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        app_items = [c for c in data if c["is_app_user"]]
        non_app_items = [c for c in data if not c["is_app_user"]]
        assert len(app_items) == 1
        assert len(non_app_items) == 1

    async def test_sms_invitation_fields_serialized(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550014", "GetList7")
        m = await _add_non_app(db_session, user.id, "SmsTarget", "+14085550015")
        m.sms_invitation_sent = True
        m.sms_invitation_sent_at = datetime.now(UTC)
        m.sms_message_id = "SM_test_123"
        db_session.add(m)
        await db_session.commit()

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()[0]
        assert data["sms_invitation_sent"] is True
        assert data["sms_invitation_sent_at"] is not None
        assert data["sms_message_id"] == "SM_test_123"

    async def test_accepted_at_serialized(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+14085550016", "GetList8")
        cu = await _make_user(db_session, "+14085550017", "AcceptedPal")
        m = await _add_app_contact(db_session, user.id, cu.id)
        await crud_circle_of_trust.accept_invitation(db_session, contact=m)
        await db_session.commit()

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()[0]
        assert data["accepted_at"] is not None

    async def test_empty_circle(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+14085550018", "EmptyCircle")

        r = await client.get(BASE, headers=_auth(user))
        assert r.status_code == 200
        assert r.json() == []


# ===========================================================================
# 2. POST /circle/members — add_trusted_contact
# ===========================================================================


@pytest.mark.asyncio
class TestAddTrustedContact:
    async def test_add_app_user_by_phone_number(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _make_user(db_session, "+15035550001", "AddOwner1")
        await _make_user(db_session, "+15035550002", "AddTarget1")

        r = await client.post(
            BASE,
            headers=_auth(owner),
            json={
                "phone_number": "+15035550002",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["is_app_user"] is True
        assert data["contact_full_name"] == "AddTarget1"
        assert data["status"] == "pending"

    async def test_add_app_user_by_contact_phone_number(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _make_user(db_session, "+15035550003", "AddOwner2")
        await _make_user(db_session, "+15035550004", "AddTarget2")

        r = await client.post(
            BASE,
            headers=_auth(owner),
            json={
                "contact_phone_number": "+15035550004",
            },
        )
        assert r.status_code == 200
        assert r.json()["is_app_user"] is True

    async def test_add_self_400(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+15035550005", "SelfAdd")
        r = await client.post(
            BASE,
            headers=_auth(user),
            json={"phone_number": "+15035550005"},
        )
        assert r.status_code == 400
        assert "yourself" in r.json()["detail"].lower()

    async def test_add_unregistered_phone_without_name_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Unregistered phone without a nickname falls into non-app path and fails."""
        user = await _make_user(db_session, "+15035550006", "LookupFail")
        r = await client.post(
            BASE,
            headers=_auth(user),
            json={"phone_number": "+18135559999"},
        )
        assert r.status_code == 400
        assert "name" in r.json()["detail"].lower()

    async def test_add_duplicate_app_user_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _make_user(db_session, "+15035550007", "DupOwner")
        await _make_user(db_session, "+15035550008", "DupTarget")

        payload = {"phone_number": "+15035550008"}
        r1 = await client.post(BASE, headers=_auth(owner), json=payload)
        assert r1.status_code == 200
        r2 = await client.post(BASE, headers=_auth(owner), json=payload)
        assert r2.status_code == 400
        assert "already" in r2.json()["detail"].lower()

    async def test_add_opted_out_phone_returns_blocked_opt_out(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Adding a phone that previously texted STOP returns a structured
        400 with code=blocked_opt_out so mobile can render 4a inline."""
        from app.services import sms_opt_out

        owner = await _make_user(db_session, "+14155550220", "OptOutOwner")
        # Pre-existing PhoneNumber row that's been opted out.
        await _make_user(db_session, "+14155550221", "Optee")
        await sms_opt_out.record_opt_out(db_session, "+14155550221")

        r = await client.post(
            BASE,
            headers=_auth(owner),
            json={
                "nickname": "Optee",
                "contact_phone_number": "+14155550221",
            },
        )
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["code"] == "blocked_opt_out"
        assert detail["phone"] == "+14155550221"
        # opted_out_at deliberately omitted from the response —
        # see endpoint comment for rationale.
        assert "opted_out_at" not in detail

    async def test_add_phone_after_start_succeeds(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """After START clears the opt-out, adding the same phone works."""
        from app.services import sms_opt_out

        owner = await _make_user(db_session, "+14155550222", "PostStartOwner")
        await _make_user(db_session, "+14155550223", "PostStartTarget")
        await sms_opt_out.record_opt_out(db_session, "+14155550223")
        await sms_opt_out.record_opt_in(db_session, "+14155550223")

        r = await client.post(
            BASE,
            headers=_auth(owner),
            json={"phone_number": "+14155550223"},
        )
        assert r.status_code == 200

    async def test_add_non_app_user_success(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15035550009", "NonAppAdd")
        r = await client.post(
            BASE,
            headers=_auth(user),
            json={
                "nickname": "Grandma",
                "contact_phone_number": "+15035550010",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["nickname"] == "Grandma"
        assert data["is_app_user"] is False

    async def test_add_non_app_missing_name_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15035550011", "NoNameAdd")
        r = await client.post(
            BASE,
            headers=_auth(user),
            json={"contact_phone_number": "+15035550012"},
        )
        assert r.status_code == 400
        assert "name" in r.json()["detail"].lower()

    async def test_add_non_app_missing_phone_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15035550013", "NoPhoneAdd")
        r = await client.post(
            BASE,
            headers=_auth(user),
            json={"nickname": "Someone"},
        )
        assert r.status_code == 400
        assert "phone" in r.json()["detail"].lower()

    async def test_add_duplicate_non_app_by_phone_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15035550014", "DupNonApp")
        payload = {
            "nickname": "Dup",
            "contact_phone_number": "+15035550015",
        }
        r1 = await client.post(BASE, headers=_auth(user), json=payload)
        assert r1.status_code == 200
        r2 = await client.post(BASE, headers=_auth(user), json=payload)
        assert r2.status_code == 400
        assert "already" in r2.json()["detail"].lower()

    async def test_add_duplicate_non_app_by_phone_contact_id(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15035550016", "DupById")
        payload = {
            "nickname": "IdDup",
            "contact_phone_number": "+15035550017",
            "phone_contact_id": "device-abc-42",
        }
        r1 = await client.post(BASE, headers=_auth(user), json=payload)
        assert r1.status_code == 200
        r2 = await client.post(BASE, headers=_auth(user), json=payload)
        assert r2.status_code == 400

    async def test_max_contacts_limit_400(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        """Exceeding MAX_TRUSTED_CONTACTS (default 3) returns 400."""
        user = await _make_user(db_session, "+15035550020", "MaxLimit")
        for i in range(3):
            cu = await _make_user(db_session, f"+1617003010{i}", f"LimitC{i}")
            m = await _add_app_contact(db_session, user.id, cu.id)
            await crud_circle_of_trust.accept_invitation(db_session, contact=m)
        await db_session.commit()

        r = await client.post(
            BASE,
            headers=_auth(user),
            json={
                "nickname": "OneMore",
                "contact_phone_number": "+15035559999",
            },
        )
        assert r.status_code == 400
        assert "maximum" in r.json()["detail"].lower()


# ===========================================================================
# 3. DELETE /{contact_id}
# ===========================================================================


@pytest.mark.asyncio
class TestRemoveContact:
    async def test_remove_success(self, client: AsyncClient, db_session: AsyncSession):
        user = await _make_user(db_session, "+18185550001", "RemOwner")
        m = await _add_non_app(db_session, user.id, "ToRemove", "+18185550002")

        r = await client.delete(f"{BASE}/{m.id}", headers=_auth(user))
        assert r.status_code == 200
        assert "removed" in r.json()["detail"].lower()

    async def test_remove_not_found_404(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+18185550003", "Rem404")
        r = await client.delete(f"{BASE}/{uuid.uuid4()}", headers=_auth(user))
        assert r.status_code == 404

    async def test_remove_other_users_contact_403(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner = await _make_user(db_session, "+18185550004", "RemReal")
        other = await _make_user(db_session, "+18185550005", "RemOther")
        m = await _add_non_app(db_session, owner.id, "Protected", "+18185550006")

        r = await client.delete(f"{BASE}/{m.id}", headers=_auth(other))
        assert r.status_code == 403


# ===========================================================================
# 4. GET /settings
# ===========================================================================


@pytest.mark.asyncio
class TestGetSettings:
    async def test_get_settings_creates_defaults(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+18045550001", "SettingsGet")
        r = await client.get(SETTINGS_BASE, headers=_auth(user))
        assert r.status_code == 200
        data = r.json()
        assert data["sms_invitations_enabled"] is True
        assert data["auto_import_contacts"] is False
        assert data["max_contacts"] == 3
        assert data["user_id"] == str(user.id)

    async def test_get_settings_returns_existing(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+18045550002", "SettingsExist")
        r1 = await client.get(SETTINGS_BASE, headers=_auth(user))
        assert r1.status_code == 200
        id1 = r1.json()["id"]

        r2 = await client.get(SETTINGS_BASE, headers=_auth(user))
        assert r2.status_code == 200
        assert r2.json()["id"] == id1


# ===========================================================================
# 5. PUT /settings
# ===========================================================================


@pytest.mark.asyncio
class TestUpdateSettings:
    async def test_update_settings_full(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15055550001", "SettingsUpd")
        r = await client.put(
            SETTINGS_BASE,
            headers=_auth(user),
            json={
                "max_contacts": 7,
                "sms_invitations_enabled": False,
                "auto_import_contacts": True,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["max_contacts"] == 7
        assert data["sms_invitations_enabled"] is False
        assert data["auto_import_contacts"] is True

    async def test_update_settings_partial(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15055550002", "SettingsPart")
        await client.get(SETTINGS_BASE, headers=_auth(user))

        r = await client.put(
            SETTINGS_BASE,
            headers=_auth(user),
            json={"max_contacts": 10},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["max_contacts"] == 10
        assert data["sms_invitations_enabled"] is True
        assert data["auto_import_contacts"] is False

    async def test_update_notification_preferences(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        user = await _make_user(db_session, "+15055550003", "SettingsNotif")
        prefs = {"push": True, "sms": False, "email": True}
        r = await client.put(
            SETTINGS_BASE,
            headers=_auth(user),
            json={"notification_preferences": prefs},
        )
        assert r.status_code == 200
        assert r.json()["notification_preferences"] == prefs
