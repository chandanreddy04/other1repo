"""Admin-managed account grants.

An enabled AccountGrant gives an account lifetime comp access on login, and — if
it carries an `otp_code` — a fixed-code login with no SMS (store reviewers).
Empty `otp_code` → standard SMS OTP but still comped. Disabled/absent → nothing.

Related: app/models/account_grant.py, app/crud/account_grant.py,
app/services/otp.py, app/services/subscription_service.py (ensure_comp_access),
app/api/v1/endpoints/auth.py, app/web/admin_registry.py.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.account_grant import crud_account_grant
from app.crud.phone_number import crud_phone_number
from app.models.account_grant import AccountGrant
from app.models.otp import OTP
from app.models.phone_number import PhoneNumber
from app.models.subscription import (
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.services import subscription_service
from app.services.otp import otp_service
from tests.helpers import create_test_user

REVIEW_PHONE = "+12345678900"
REVIEW_CODE = "680684"


async def _make_grant(
    db: AsyncSession,
    phone: str,
    *,
    otp_code: str | None = None,
    enabled: bool = True,
    label: str = "test",
) -> AccountGrant:
    phone_obj, _ = await crud_phone_number.get_or_create(db, number=phone)
    grant = AccountGrant(
        phone_number_id=phone_obj.id,
        label=label,
        otp_code=otp_code,
        enabled=enabled,
    )
    db.add(grant)
    await db.commit()
    await db.refresh(grant)
    return grant


@pytest.mark.asyncio
class TestGrantLookup:
    async def test_returns_enabled_grant(self, db_session: AsyncSession):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE)
        grant = await crud_account_grant.get_enabled_by_phone(
            db_session, phone_number=REVIEW_PHONE
        )
        assert grant is not None
        assert grant.otp_code == REVIEW_CODE

    async def test_none_when_disabled(self, db_session: AsyncSession):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE, enabled=False)
        grant = await crud_account_grant.get_enabled_by_phone(
            db_session, phone_number=REVIEW_PHONE
        )
        assert grant is None

    async def test_none_when_absent(self, db_session: AsyncSession):
        grant = await crud_account_grant.get_enabled_by_phone(
            db_session, phone_number="+14155559999"
        )
        assert grant is None


@pytest.mark.asyncio
class TestOtpBypass:
    async def test_grant_with_code_stores_fixed_code_no_sms(
        self, db_session: AsyncSession, monkeypatch
    ):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE)
        send_sms = AsyncMock()
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", send_sms)

        ok, _ = await otp_service.send_otp(db_session, REVIEW_PHONE)

        assert ok is True
        send_sms.assert_not_called()
        stored = (
            await db_session.execute(
                select(OTP).where(OTP.phone_number == REVIEW_PHONE)
            )
        ).scalars().all()
        assert len(stored) == 1
        assert stored[0].otp_code == REVIEW_CODE

    async def test_grant_with_code_verify_succeeds(
        self, db_session: AsyncSession, monkeypatch
    ):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE)
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", AsyncMock())

        await otp_service.send_otp(db_session, REVIEW_PHONE)
        ok, _ = await otp_service.verify_otp(db_session, REVIEW_PHONE, REVIEW_CODE)
        assert ok is True

    async def test_grant_with_code_verify_wrong_fails(
        self, db_session: AsyncSession, monkeypatch
    ):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE)
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", AsyncMock())

        await otp_service.send_otp(db_session, REVIEW_PHONE)
        ok, _ = await otp_service.verify_otp(db_session, REVIEW_PHONE, "000000")
        assert ok is False

    async def test_grant_without_code_uses_normal_sms(
        self, db_session: AsyncSession, monkeypatch
    ):
        # Comp-only grant (no otp_code) must NOT bypass — standard SMS path.
        await _make_grant(db_session, REVIEW_PHONE, otp_code=None)
        monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
        result = MagicMock()
        result.success = True
        send_sms = AsyncMock(return_value=result)
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", send_sms)

        ok, _ = await otp_service.send_otp(db_session, REVIEW_PHONE)

        assert ok is True
        send_sms.assert_called_once()
        stored = (
            await db_session.execute(
                select(OTP).where(OTP.phone_number == REVIEW_PHONE)
            )
        ).scalars().one()
        assert stored.otp_code.isdigit() and len(stored.otp_code) == 6

    async def test_disabled_grant_with_code_does_not_bypass(
        self, db_session: AsyncSession, monkeypatch
    ):
        await _make_grant(
            db_session, REVIEW_PHONE, otp_code="999999", enabled=False
        )
        monkeypatch.setattr("app.core.config.settings.ENVIRONMENT", "production")
        result = MagicMock()
        result.success = True
        send_sms = AsyncMock(return_value=result)
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", send_sms)

        ok, _ = await otp_service.send_otp(db_session, REVIEW_PHONE)

        assert ok is True
        send_sms.assert_called_once()
        stored = (
            await db_session.execute(
                select(OTP).where(OTP.phone_number == REVIEW_PHONE)
            )
        ).scalars().one()
        assert stored.otp_code != "999999"


@pytest.mark.asyncio
class TestEnsureCompAccess:
    async def test_grants_comp_subscription(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session, phone_number=REVIEW_PHONE, full_name="App Reviewer"
        )
        await subscription_service.ensure_comp_access(
            db_session, REVIEW_PHONE, user.id
        )

        sub = await subscription_service.get_active_subscription(db_session, user.id)
        assert sub is not None
        assert sub.source == SubscriptionSource.COMP
        assert sub.status == SubscriptionStatus.ACTIVE

    async def test_idempotent(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session, phone_number=REVIEW_PHONE, full_name="App Reviewer"
        )
        await subscription_service.ensure_comp_access(db_session, REVIEW_PHONE, user.id)
        await subscription_service.ensure_comp_access(db_session, REVIEW_PHONE, user.id)

        subs = (
            await db_session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.source == SubscriptionSource.COMP.value,
                )
            )
        ).scalars().all()
        assert len(subs) == 1


@pytest.mark.asyncio
class TestLoginFlow:
    async def _patch_stripe(self, monkeypatch):
        monkeypatch.setattr(
            "app.services.stripe_service.find_existing_customer_by_phone",
            lambda *a, **k: None,
        )
        monkeypatch.setattr(
            "app.services.stripe_service.get_or_create_stripe_customer", AsyncMock()
        )

    async def _comp_sub_for(self, db_session, phone):
        return (
            await db_session.execute(
                select(Subscription)
                .join(PhoneNumber, Subscription.phone_number_id == PhoneNumber.id)
                .where(
                    PhoneNumber.number == phone,
                    Subscription.source == SubscriptionSource.COMP.value,
                )
            )
        ).scalars().first()

    async def test_bypass_login_grants_comp(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        await _make_grant(db_session, REVIEW_PHONE, otp_code=REVIEW_CODE)
        monkeypatch.setattr("app.services.otp.sms_service.send_sms", AsyncMock())
        await self._patch_stripe(monkeypatch)

        r1 = await client.post(
            "/api/v1/auth/request-otp", json={"phone_number": REVIEW_PHONE}
        )
        assert r1.status_code == 200
        r2 = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone_number": REVIEW_PHONE, "otp_code": REVIEW_CODE},
        )
        assert r2.status_code == 200

        sub = await self._comp_sub_for(db_session, REVIEW_PHONE)
        assert sub is not None
        assert sub.status == SubscriptionStatus.ACTIVE

    async def test_comp_only_grant_login_grants_comp(
        self, client: AsyncClient, db_session: AsyncSession, monkeypatch
    ):
        # No otp_code → normal SMS OTP, but login still comps the account.
        await _make_grant(db_session, REVIEW_PHONE, otp_code=None)
        monkeypatch.setattr(
            "app.services.otp.sms_service.send_sms",
            AsyncMock(return_value=MagicMock(success=True)),
        )
        await self._patch_stripe(monkeypatch)

        r1 = await client.post(
            "/api/v1/auth/request-otp", json={"phone_number": REVIEW_PHONE}
        )
        assert r1.status_code == 200
        code = (
            await db_session.execute(
                select(OTP).where(OTP.phone_number == REVIEW_PHONE)
            )
        ).scalars().first().otp_code

        r2 = await client.post(
            "/api/v1/auth/verify-otp",
            json={"phone_number": REVIEW_PHONE, "otp_code": code},
        )
        assert r2.status_code == 200

        sub = await self._comp_sub_for(db_session, REVIEW_PHONE)
        assert sub is not None


@pytest.mark.asyncio
class TestAdminCreate:
    async def test_create_resolves_phone_string_to_fk(
        self, client: AsyncClient, admin_cookies: dict, db_session: AsyncSession
    ):
        # The admin form takes a phone STRING; form_transform must resolve it to
        # a phone_number_id FK (AccountGrant has no phone string column).
        from app.web.csrf import (
            CSRF_COOKIE_NAME,
            CSRF_FORM_FIELD,
            generate_csrf_token,
        )

        token = generate_csrf_token()
        resp = await client.post(
            "/admin/account-grants",
            data={
                CSRF_FORM_FIELD: token,
                "phone_number": REVIEW_PHONE,
                "label": "App Store reviewer",
                "otp_code": REVIEW_CODE,
                "enabled": "true",
            },
            cookies={**admin_cookies, CSRF_COOKIE_NAME: token},
        )
        assert resp.status_code in (200, 303)

        grant = await crud_account_grant.get_enabled_by_phone(
            db_session, phone_number=REVIEW_PHONE
        )
        assert grant is not None
        assert grant.otp_code == REVIEW_CODE
        assert grant.phone_number == REVIEW_PHONE
