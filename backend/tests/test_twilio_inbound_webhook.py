"""Tests for the inbound Twilio SMS webhook.

Covers the routing tree: protected STOP/START keywords vs. soft-stop
intent vs. other. Push fanout and SMS dispatch are mocked — the cascade
and chooser logic have dedicated tests in test_circle_cascade_notifications.

Related: app/api/v1/endpoints/inbound_sms.py.
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.services import sms_opt_out
from app.services.sms import SMSResult
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _sms_ok() -> SMSResult:
    return SMSResult(success=True, message_id="sm_x", error=None)


async def _add_phone_contact(
    db: AsyncSession, owner, contact_phone: str, name: str
) -> CircleOfTrustMember:
    phone, _ = await crud_phone_number.get_or_create(db, number=contact_phone)
    m = CircleOfTrustMember(
        user_id=owner.id,
        nickname=name,
        contact_phone_number_id=phone.id,
        status=ContactStatus.ACTIVE,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def test_stop_keyword_records_opt_out_and_cascades(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(db_session, phone_number="+12125550001")
    owner.expo_push_token = "ExponentPushToken[owner]"
    await _add_phone_contact(db_session, owner, "+12125550002", "Bob")
    await db_session.commit()

    with patch(
        "app.api.v1.endpoints.inbound_sms.fan_out_cascade_notifications",
        new=AsyncMock(),
    ) as mock_fanout:
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550002", "Body": "STOP"},
        )
    assert response.status_code == 200
    assert "<Response" in response.text
    assert await sms_opt_out.is_opted_out(db_session, "+12125550002")
    mock_fanout.assert_awaited_once()


async def test_start_keyword_restores_membership(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(db_session, phone_number="+12125550010")
    member = await _add_phone_contact(db_session, owner, "+12125550011", "Bob")
    # Pre-opt-out so START has something to restore.
    pn, _ = await crud_phone_number.get_or_create(db_session, number="+12125550011")
    await sms_opt_out.record_opt_out(db_session, "+12125550011")
    await sms_opt_out.cascade_circle_removal(db_session, pn)
    await db_session.refresh(member)
    assert member.status == ContactStatus.OPTED_OUT

    response = await client.post(
        "/webhooks/sms/twilio-inbound",
        data={"From": "+12125550011", "Body": "start"},
    )
    assert response.status_code == 200
    await db_session.refresh(member)
    assert member.status == ContactStatus.ACTIVE
    assert not await sms_opt_out.is_opted_out(db_session, "+12125550011")


async def test_soft_stop_intent_sends_gate_sms(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(
        db_session, phone_number="+12125550020", full_name="Alice"
    )
    await _add_phone_contact(db_session, owner, "+12125550021", "Bob")

    with patch(
        "app.api.v1.endpoints.inbound_sms.sms_service.send_sms",
        new=AsyncMock(return_value=_sms_ok()),
    ) as mock_send:
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550021", "Body": "please stop"},
        )
    assert response.status_code == 200
    mock_send.assert_awaited_once()
    sent_body = mock_send.await_args.kwargs["message"]
    # Gate A names the (single) owner — owner-approved 2026-09-27.
    assert "Alice" in sent_body
    assert "Alice's Circle of Trust" in sent_body
    assert "STOP to confirm" in sent_body
    # Cooldown stamp set.
    assert not await sms_opt_out.should_send_soft_stop_gate(
        db_session, "+12125550021"
    )
    # Did NOT record opt-out — the gate is a confirmation step, not an action.
    assert not await sms_opt_out.is_opted_out(db_session, "+12125550021")


async def test_soft_stop_respects_cooldown(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    await create_test_user(db_session, phone_number="+12125550030")
    await sms_opt_out.record_soft_stop_gate_sent(db_session, "+12125550030")

    with patch(
        "app.api.v1.endpoints.inbound_sms.sms_service.send_sms",
        new=AsyncMock(return_value=_sms_ok()),
    ) as mock_send:
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550030", "Body": "leave me alone"},
        )
    assert response.status_code == 200
    mock_send.assert_not_awaited()


async def test_irrelevant_body_is_acked_with_no_action(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    await create_test_user(db_session, phone_number="+12125550040")
    with patch(
        "app.api.v1.endpoints.inbound_sms.sms_service.send_sms",
        new=AsyncMock(return_value=_sms_ok()),
    ) as mock_send, patch(
        "app.api.v1.endpoints.inbound_sms.fan_out_cascade_notifications",
        new=AsyncMock(),
    ) as mock_fanout:
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550040", "Body": "hi! who is this?"},
        )
    assert response.status_code == 200
    assert "<Response" in response.text
    mock_send.assert_not_awaited()
    mock_fanout.assert_not_awaited()
    assert not await sms_opt_out.is_opted_out(db_session, "+12125550040")


async def test_missing_from_returns_empty_twiml(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/webhooks/sms/twilio-inbound",
        data={"Body": "STOP"},
    )
    assert response.status_code == 200
    assert "<Response" in response.text


async def test_stop_from_unknown_phone_logs_but_ok(
    client: AsyncClient,
) -> None:
    # Phone we've never seen. Twilio honors the STOP on their side; we
    # just have no memberships to cascade.
    response = await client.post(
        "/webhooks/sms/twilio-inbound",
        data={"From": "+14085558888", "Body": "STOP"},
    )
    assert response.status_code == 200


async def test_account_holder_stop_triggers_user_directed_push(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    """STOP from a phone tied to a Made It Home User row fires an
    `account_holder_unsubscribed` push to the user — distinct from the
    cascade pushes to circle owners. They've effectively unsubscribed
    from the app, not just from being someone's emergency contact."""
    account_user = await create_test_user(
        db_session, phone_number="+12125550070", full_name="Alex"
    )
    account_user.expo_push_token = "ExponentPushToken[acct]"
    await db_session.commit()

    with patch(
        "app.api.v1.endpoints.inbound_sms.fan_out_cascade_notifications",
        new=AsyncMock(),
    ), patch(
        "app.api.v1.endpoints.inbound_sms.send_account_holder_unsubscribed",
        new=AsyncMock(),
    ) as mock_push:
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550070", "Body": "STOP"},
        )
    assert response.status_code == 200
    mock_push.assert_awaited_once()
    # Confirms it was awaited with the User row, not a different one.
    awaited_user = mock_push.await_args.args[1]
    assert awaited_user.id == account_user.id


async def test_invalid_signature_rejected_when_token_configured(
    db_session: AsyncSession, client: AsyncClient, monkeypatch
) -> None:
    """When TWILIO_AUTH_TOKEN is configured, an inbound request with a
    missing/wrong X-Twilio-Signature header gets a 403, not a silent
    pass-through. This is the primary defense against forged STOPs."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "ACfake_token_for_test")
    response = await client.post(
        "/webhooks/sms/twilio-inbound",
        data={"From": "+12125550060", "Body": "STOP"},
        headers={"X-Twilio-Signature": "obviously-not-a-real-signature"},
    )
    assert response.status_code == 403


async def test_misconfigured_token_in_production_fails_closed(
    client: AsyncClient, monkeypatch
) -> None:
    """In production, an empty / placeholder token means the deploy
    is misconfigured. Refuse to serve rather than silently skip
    signature validation — the open-cascade blast radius is bigger
    than the brief unavailability."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = await client.post(
        "/webhooks/sms/twilio-inbound",
        data={"From": "+12125550070", "Body": "STOP"},
    )
    assert response.status_code == 503


async def test_unsubscribe_keyword_treated_as_stop(
    db_session: AsyncSession, client: AsyncClient
) -> None:
    owner = await create_test_user(db_session, phone_number="+12125550050")
    owner.expo_push_token = "ExponentPushToken[o]"
    await _add_phone_contact(db_session, owner, "+12125550051", "Bob")
    await db_session.commit()

    with patch(
        "app.api.v1.endpoints.inbound_sms.fan_out_cascade_notifications",
        new=AsyncMock(),
    ):
        response = await client.post(
            "/webhooks/sms/twilio-inbound",
            data={"From": "+12125550051", "Body": "Unsubscribe"},
        )
    assert response.status_code == 200
    assert await sms_opt_out.is_opted_out(db_session, "+12125550051")
