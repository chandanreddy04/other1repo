"""No-app contact flows: web circle acceptance + public alert page + claim.

Covers the 2026-07-02 flow-review decisions (docs/flow-review.md §4.2
B1/3.2, §4.3 3.3, §2.3): a contact without the app can accept an invite on
the web (explicit consent → ACTIVE → alertable), and an SMS-only recipient
can see alert details and claim ("I'm on it") via the tokenized public
alert page — with the claim broadcast to the owner.

Related: app/web/routes_web.py, app/services/circle_invitations.py,
app/services/alert_acknowledgement.py.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from app.models.user import User
from tests.helpers import create_test_user


def _cookies(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


async def _inviter_with_pending_invite(
    db: AsyncSession, inviter_phone: str, contact_phone: str
) -> tuple[User, User, CircleOfTrustMember]:
    inviter = await create_test_user(
        db,
        phone_number=inviter_phone,
        full_name="Ivy Inviter",
        # create_test_user doesn't generate one; unique per test via phone.
        circle_invite_code=f"WB{inviter_phone[-6:]}",
    )
    contact = await create_test_user(
        db, phone_number=contact_phone, full_name="Cody Contact"
    )
    member = CircleOfTrustMember(
        user_id=inviter.id,
        contact_phone_number_id=contact.phone_number_id,
        nickname="Cody",
        status=ContactStatus.PENDING.value,
    )
    db.add(member)
    await db.commit()
    await db.refresh(member)
    return inviter, contact, member


@pytest.mark.asyncio
class TestWebCircleAccept:
    async def test_lander_offers_web_accept_when_logged_out(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, _, _ = await _inviter_with_pending_invite(
            db_session, "+14155596001", "+14155596002"
        )
        resp = await client.get(f"/circles/{inviter.circle_invite_code}")
        assert resp.status_code == 200
        assert "Accept on the web" in resp.text
        assert "No app required" in resp.text

    async def test_logged_in_contact_sees_explicit_accept_form(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, contact, _ = await _inviter_with_pending_invite(
            db_session, "+14155596003", "+14155596004"
        )
        resp = await client.get(
            f"/circles/{inviter.circle_invite_code}", cookies=_cookies(contact)
        )
        assert resp.status_code == 200
        assert "Yes, I'll join their Circle" in resp.text
        # Explicit-consent disclosure (owner decision 3.2).
        assert "agree to receive safety alert texts" in resp.text

    async def test_web_accept_activates_membership_and_sends_welcome_sms(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, contact, member = await _inviter_with_pending_invite(
            db_session, "+14155596005", "+14155596006"
        )
        # circle_invitations imports the sender at call time — patch the
        # source module so the deferred import resolves to the mock.
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ) as mock_welcome:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/accept",
                cookies=_cookies(contact),
                follow_redirects=False,
            )
        # PRG: the accept POST always redirects back to the GET lander
        # (?accepted=1 marks the just-accepted state for the referral offer).
        assert resp.status_code == 303
        assert resp.headers["location"] == (
            f"/circles/{inviter.circle_invite_code}?accepted=1"
        )
        page = await client.get(resp.headers["location"], cookies=_cookies(contact))
        assert page.status_code == 200
        assert "You're in!" in page.text
        # DND-bypass guidance surfaces on success (flow-review §4.4b).
        assert "Emergency Bypass" in page.text
        assert "/made-it-home.vcf" in page.text
        await db_session.refresh(member)
        assert member.status == ContactStatus.ACTIVE
        mock_welcome.assert_awaited_once()

    async def test_web_accept_code_is_case_insensitive(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, contact, member = await _inviter_with_pending_invite(
            db_session, "+14155596011", "+14155596012"
        )
        with patch(
            "app.services.notification_helpers.send_circle_welcome_sms",
            new_callable=AsyncMock,
        ):
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code.lower()}/accept",
                cookies=_cookies(contact),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        page = await client.get(resp.headers["location"], cookies=_cookies(contact))
        assert page.status_code == 200
        assert "You're in!" in page.text
        await db_session.refresh(member)
        assert member.status == ContactStatus.ACTIVE

    async def test_web_accept_unknown_code_renders_invalid_link(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        contact = await create_test_user(
            db_session, phone_number="+14155596013", full_name="Cody Contact"
        )
        resp = await client.post(
            "/circles/NOSUCHCODE/accept",
            cookies=_cookies(contact),
            follow_redirects=True,
        )
        assert resp.status_code == 200
        assert "This invite link isn't valid" in resp.text

    async def test_web_accept_requires_login(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        inviter, _, _ = await _inviter_with_pending_invite(
            db_session, "+14155596007", "+14155596008"
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/accept", follow_redirects=False
        )
        assert resp.status_code == 302
        assert "/login?next=/circles/" in resp.headers["location"]

    async def test_vcard_download(self, client: AsyncClient):
        resp = await client.get("/made-it-home.vcf")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/vcard")
        assert "Made It Home Alerts" in resp.text
        assert "Emergency Bypass" in resp.text


async def _session_with_alert(
    db: AsyncSession,
    owner_phone: str,
    contact_phone: str,
    *,
    session_status: str = SessionStatus.MISSED.value,
    alert_type: AlertType = AlertType.MISSED_SESSION,
) -> tuple[User, Alert]:
    owner = await create_test_user(db, phone_number=owner_phone, full_name="Ana Owner")
    contact = await create_test_user(
        db, phone_number=contact_phone, full_name="Cody Contact"
    )
    db.add(
        CircleOfTrustMember(
            user_id=owner.id,
            contact_phone_number_id=contact.phone_number_id,
            nickname="Cody",
            status=ContactStatus.ACTIVE.value,
        )
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        destination="Central Park",
        status=session_status,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    alert = Alert(
        session_id=session.id,
        sent_to_phone_id=contact.phone_number_id,
        alert_type=alert_type,
        status=AlertStatus.SENT,
        message="test",
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)
    return owner, alert


@pytest.mark.asyncio
class TestPublicAlertPage:
    async def test_alert_page_shows_details_and_actions(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _session_with_alert(db_session, "+14155596101", "+14155596102")
        # A second notified contact — the Acknowledge button only shows when
        # more than one contact was alerted (nobody to signal otherwise).
        # See TestClaimVisibility for the single-contact case.
        contact2 = await create_test_user(
            db_session, phone_number="+14155596109", full_name="Dee Contact"
        )
        db_session.add(
            Alert(
                session_id=alert.session_id,
                sent_to_phone_id=contact2.phone_number_id,
                alert_type=AlertType.MISSED_SESSION,
                status=AlertStatus.SENT,
                message="test",
            )
        )
        await db_session.commit()
        resp = await client.get(f"/alerts/{alert.id}")
        assert resp.status_code == 200
        assert "Ana missed their check-in" in resp.text
        assert "tel:+14155596101" in resp.text
        assert "Central Park" in resp.text
        assert "Acknowledge" in resp.text
        assert "call 911" in resp.text

    async def test_sos_alert_page_is_distinct(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _session_with_alert(
            db_session,
            "+14155596103",
            "+14155596104",
            alert_type=AlertType.PANIC,
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "Ana pressed SOS" in resp.text
        assert "needs help now" in resp.text

    async def test_all_clear_state_after_completion(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        _, alert = await _session_with_alert(
            db_session,
            "+14155596105",
            "+14155596106",
            session_status=SessionStatus.COMPLETED.value,
        )
        resp = await client.get(f"/alerts/{alert.id}")
        assert "All clear" in resp.text
        assert "marked themselves safe" in resp.text

    async def test_invalid_token_shows_not_found(self, client: AsyncClient):
        resp = await client.get("/alerts/not-a-uuid")
        assert resp.status_code == 200
        assert "isn't valid" in resp.text

    async def test_claim_acknowledges_and_notifies_owner(
        self, client: AsyncClient, db_session: AsyncSession
    ):
        owner, alert = await _session_with_alert(
            db_session, "+14155596107", "+14155596108"
        )
        # A second notified contact so the Acknowledge control is visible
        # (it only renders when >1 contact was alerted).
        contact2 = await create_test_user(
            db_session, phone_number="+14155596110", full_name="Eve Contact"
        )
        db_session.add(
            Alert(
                session_id=alert.session_id,
                sent_to_phone_id=contact2.phone_number_id,
                alert_type=AlertType.MISSED_SESSION,
                status=AlertStatus.SENT,
                message="test",
            )
        )
        await db_session.commit()

        resp = await client.post(f"/alerts/{alert.id}/acknowledge")

        # PRG: the POST answers 303 back to the GET page so the browser never
        # sits parked on a re-submittable POST (the form submit is script-free).
        assert resp.status_code == 303
        assert resp.headers["location"] == f"/alerts/{alert.id}"
        page = await client.get(resp.headers["location"])
        # The checked, grayed-out button IS the whole acknowledgement UI —
        # no badges, no "on it" copy anywhere (owner decision 2026-07-18).
        assert "✓ Acknowledged" in page.text
        assert "on it" not in page.text
        await db_session.refresh(alert)
        assert alert.status == AlertStatus.ACKNOWLEDGED
        assert alert.acknowledged_at is not None
        # The broadcast is SMS-only: the owner gets a NAMED acknowledgement
        # SMS via the outbox; no push rows are created at all.
        rows = (
            (
                await db_session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.session_id == alert.session_id,
                        NotificationDelivery.kind
                        == NotificationKind.ALERT_ACKNOWLEDGED,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert rows and all(r.channel == DeliveryChannel.SMS for r in rows)
        owner_rows = [r for r in rows if r.recipient_phone_id == owner.phone_number_id]
        assert owner_rows
        assert "Cody acknowledged your alert" in owner_rows[0].body
