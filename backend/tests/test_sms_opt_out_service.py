"""Tests for the SMS opt-out engine.

Covers: opt-out / opt-in roundtrip, cascade to circle memberships across
both join paths (phone-only contact, app-user contact), sender-profile
case picking for the soft-stop gate, the soft-stop intent matcher, and
the 24h cooldown.

Related: app/services/sms_opt_out.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.services import sms_opt_out
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


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


async def _add_user_contact(
    db: AsyncSession, owner, contact_user
) -> CircleOfTrustMember:
    m = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact_user.phone_number_id,
        nickname=contact_user.full_name,
        status=ContactStatus.ACTIVE,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def test_soft_stop_intent_matches_phrases() -> None:
    assert sms_opt_out.soft_stop_intent("please stop")
    assert sms_opt_out.soft_stop_intent("Please STOP texting me")
    assert sms_opt_out.soft_stop_intent("don't text me")
    assert sms_opt_out.soft_stop_intent("don’t text me")  # noqa: RUF001 - curly apostrophe is the test case
    assert sms_opt_out.soft_stop_intent("Leave me alone now")
    assert not sms_opt_out.soft_stop_intent("STOP")
    assert not sms_opt_out.soft_stop_intent("hi there")
    assert not sms_opt_out.soft_stop_intent(None)
    assert not sms_opt_out.soft_stop_intent("")


async def test_record_opt_out_is_idempotent(db_session: AsyncSession) -> None:
    user = await create_test_user(db_session, phone_number="+14155550001")
    pn1 = await sms_opt_out.record_opt_out(db_session, "+14155550001")
    assert pn1 is not None
    first = pn1.sms_opted_out_at
    assert first is not None
    # Second call should NOT bump the timestamp (preserves audit trail).
    pn2 = await sms_opt_out.record_opt_out(db_session, "+14155550001")
    assert pn2 is not None
    assert pn2.sms_opted_out_at == first
    assert await sms_opt_out.is_opted_out(db_session, "+14155550001")
    _ = user


async def test_opt_in_clears_state_and_restores_memberships(
    db_session: AsyncSession,
) -> None:
    owner = await create_test_user(db_session, phone_number="+14155550010")
    member = await _add_phone_contact(
        db_session, owner, "+14155550011", "Bob"
    )

    # STOP cascades; START restores.
    await sms_opt_out.record_opt_out(db_session, "+14155550011")
    pn = await crud_phone_number.get_or_create(db_session, number="+14155550011")
    impacts = await sms_opt_out.cascade_circle_removal(db_session, pn[0])
    assert len(impacts) == 1
    await db_session.refresh(member)
    assert member.status == ContactStatus.OPTED_OUT
    assert member.opted_out_at is not None

    await sms_opt_out.record_opt_in(db_session, "+14155550011")
    await db_session.refresh(member)
    assert member.status == ContactStatus.ACTIVE
    assert member.opted_out_at is None
    assert not await sms_opt_out.is_opted_out(db_session, "+14155550011")


async def test_cascade_phone_only_contact_path(db_session: AsyncSession) -> None:
    owner_a = await create_test_user(db_session, phone_number="+14155550020")
    owner_b = await create_test_user(db_session, phone_number="+14155550021")
    await _add_phone_contact(db_session, owner_a, "+14155550022", "Bob")
    await _add_phone_contact(db_session, owner_b, "+14155550022", "Bob")

    pn, _ = await crud_phone_number.get_or_create(db_session, number="+14155550022")
    impacts = await sms_opt_out.cascade_circle_removal(db_session, pn)

    owner_ids = {i.owner.id for i in impacts}
    assert owner_ids == {owner_a.id, owner_b.id}
    for i in impacts:
        assert i.contact_name == "Bob"
        assert i.remaining_active_count == 0
        assert i.has_active_session is False


async def test_cascade_remaining_count_when_owner_has_others(
    db_session: AsyncSession,
) -> None:
    """Owner with N contacts → one opts out → remaining_active_count is N-1."""
    owner = await create_test_user(db_session, phone_number="+14155550025")
    await _add_phone_contact(db_session, owner, "+14155550026", "Bob")
    await _add_phone_contact(db_session, owner, "+14155550027", "Carol")
    await _add_phone_contact(db_session, owner, "+14155550028", "Dan")

    pn, _ = await crud_phone_number.get_or_create(db_session, number="+14155550026")
    impacts = await sms_opt_out.cascade_circle_removal(db_session, pn)
    assert len(impacts) == 1
    assert impacts[0].remaining_active_count == 2


async def test_cascade_handles_pending_status(db_session: AsyncSession) -> None:
    """PENDING memberships (invited but not yet accepted) cascade too."""
    owner = await create_test_user(db_session, phone_number="+14155550029")
    phone, _ = await crud_phone_number.get_or_create(db_session, number="+14155550034")
    pending = CircleOfTrustMember(
        user_id=owner.id,
        nickname="Pending Bob",
        contact_phone_number_id=phone.id,
        status=ContactStatus.PENDING,
    )
    db_session.add(pending)
    await db_session.commit()

    impacts = await sms_opt_out.cascade_circle_removal(db_session, phone)
    assert len(impacts) == 1
    await db_session.refresh(pending)
    assert pending.status == ContactStatus.OPTED_OUT


async def test_soft_stop_intent_handles_internal_whitespace() -> None:
    """Newlines/double-spaces inside a phrase still match — carriers
    sometimes line-wrap inbound messages."""
    assert sms_opt_out.soft_stop_intent("please\nstop")
    assert sms_opt_out.soft_stop_intent("please   stop")
    assert sms_opt_out.soft_stop_intent("Please\tstop texting me")
    assert sms_opt_out.soft_stop_intent("don't\ntext me")


async def test_sender_profile_single_owner_with_null_name(
    db_session: AsyncSession,
) -> None:
    """Single owner whose full_name is NULL still gets the single-owner
    template (with a fallback phrase) instead of falling into multi-owner
    grammar like 'for 1 people'."""
    owner = await create_test_user(
        db_session, phone_number="+14155550035", full_name=None
    )
    await _add_phone_contact(db_session, owner, "+14155550036", "Bob")
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550036")
    assert profile.owner_count == 1
    assert profile.owner_names == ["someone"]


async def test_cascade_app_user_contact_path(db_session: AsyncSession) -> None:
    owner = await create_test_user(db_session, phone_number="+14155550030")
    bob = await create_test_user(
        db_session, phone_number="+14155550031", full_name="Bob"
    )
    await _add_user_contact(db_session, owner, bob)

    pn, _ = await crud_phone_number.get_or_create(db_session, number="+14155550031")
    impacts = await sms_opt_out.cascade_circle_removal(db_session, pn)
    assert len(impacts) == 1
    assert impacts[0].owner.id == owner.id


async def test_cascade_picks_up_active_session(db_session: AsyncSession) -> None:
    from app.models.session import Session, SessionStatus, SessionType

    owner = await create_test_user(db_session, phone_number="+14155550040")
    await _add_phone_contact(db_session, owner, "+14155550041", "Bob")
    session = Session(
        user_id=owner.id,
        session_type=SessionType.CHECKIN,
        status=SessionStatus.ACTIVE,
        expected_return_time=datetime.now(UTC) + timedelta(hours=1),
    )
    db_session.add(session)
    await db_session.commit()

    pn, _ = await crud_phone_number.get_or_create(db_session, number="+14155550041")
    impacts = await sms_opt_out.cascade_circle_removal(db_session, pn)
    assert impacts[0].has_active_session is True
    assert impacts[0].active_session_id == session.id


async def test_sender_profile_cases(db_session: AsyncSession) -> None:
    # Case A: single owner, no account
    alice = await create_test_user(
        db_session, phone_number="+14155550050", full_name="Alice"
    )
    await _add_phone_contact(db_session, alice, "+14155550051", "Bob")
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550051")
    assert profile.owner_count == 1
    assert profile.has_account is False
    assert profile.owner_names == ["Alice"]

    # Case B: multi-owner, no account
    carol = await create_test_user(
        db_session, phone_number="+14155550052", full_name="Carol"
    )
    await _add_phone_contact(db_session, carol, "+14155550051", "Bob")
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550051")
    assert profile.owner_count == 2
    assert profile.has_account is False
    assert profile.owner_names == []  # only populated when single-owner

    # Case C: account holder, no circles
    await create_test_user(db_session, phone_number="+14155550053")
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550053")
    assert profile.owner_count == 0
    assert profile.has_account is True

    # Case D: account + contact in N circles
    dan = await create_test_user(
        db_session, phone_number="+14155550054", full_name="Dan"
    )
    await _add_user_contact(db_session, alice, dan)
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550054")
    assert profile.owner_count == 1
    assert profile.has_account is True

    # Case E: nothing on file
    profile = await sms_opt_out.get_sender_profile(db_session, "+14155550099")
    assert profile.owner_count == 0
    assert profile.has_account is False


async def test_soft_stop_cooldown_24h(db_session: AsyncSession) -> None:
    await create_test_user(db_session, phone_number="+14155550060")
    assert await sms_opt_out.should_send_soft_stop_gate(db_session, "+14155550060")
    await sms_opt_out.record_soft_stop_gate_sent(db_session, "+14155550060")
    assert not await sms_opt_out.should_send_soft_stop_gate(
        db_session, "+14155550060"
    )

    # Backdate to 25h ago — cooldown should expire.
    pn, _ = await crud_phone_number.get_or_create(db_session, number="+14155550060")
    pn.last_soft_stop_gate_sent_at = datetime.now(UTC) - timedelta(hours=25)
    await db_session.commit()
    assert await sms_opt_out.should_send_soft_stop_gate(db_session, "+14155550060")


async def test_unknown_phone_returns_false_and_none(db_session: AsyncSession) -> None:
    # Phone with no row in our DB should be treated as "not opted out" and
    # all the record_* helpers should fail silently rather than 500.
    assert not await sms_opt_out.is_opted_out(db_session, "+14155559999")
    assert await sms_opt_out.record_opt_out(db_session, "+14155559999") is None
    assert await sms_opt_out.record_opt_in(db_session, "+14155559999") is None


async def test_gated_send_sms_blocks_opted_out(db_session: AsyncSession) -> None:
    """Blocks dispatch when the target phone is opted out, returns a
    structured error rather than a generic delivery failure."""
    from unittest.mock import AsyncMock, patch

    from app.services.sms import SMSResult

    await create_test_user(db_session, phone_number="+14155550080")
    await sms_opt_out.record_opt_out(db_session, "+14155550080")

    with patch(
        "app.services.sms.sms_service.send_sms",
        new=AsyncMock(return_value=SMSResult(success=True, message_id="x")),
    ) as mock_send:
        result = await sms_opt_out.gated_send_sms(
            db_session, "+14155550080", "hello"
        )
    assert result.success is False
    assert result.error == "opted_out"
    mock_send.assert_not_awaited()


async def test_gated_send_sms_passes_through_when_not_opted_out(
    db_session: AsyncSession,
) -> None:
    """When opt-out isn't set, the wrapper delegates to sms_service."""
    from unittest.mock import AsyncMock, patch

    from app.services.sms import SMSResult

    await create_test_user(db_session, phone_number="+14155550081")

    with patch(
        "app.services.sms.sms_service.send_sms",
        new=AsyncMock(return_value=SMSResult(success=True, message_id="abc")),
    ) as mock_send:
        result = await sms_opt_out.gated_send_sms(
            db_session, "+14155550081", "hello"
        )
    assert result.success is True
    assert result.message_id == "abc"
    mock_send.assert_awaited_once()


async def test_gated_send_sms_unknown_phone_passes_through(
    db_session: AsyncSession,
) -> None:
    """Phone with no row in our DB is treated as not opted out — the
    gate doesn't accidentally drop traffic to first-touch recipients."""
    from unittest.mock import AsyncMock, patch

    from app.services.sms import SMSResult

    with patch(
        "app.services.sms.sms_service.send_sms",
        new=AsyncMock(return_value=SMSResult(success=True, message_id="z")),
    ) as mock_send:
        result = await sms_opt_out.gated_send_sms(
            db_session, "+14085550001", "hello"
        )
    assert result.success is True
    mock_send.assert_awaited_once()


async def test_record_soft_stop_gate_creates_row_for_unknown_phone(
    db_session: AsyncSession,
) -> None:
    """Without get_or_create here, an unknown phone repeatedly texting
    "please stop" would never get a cooldown stamped — silent no-op
    leaves room for them to spam our gate SMS."""
    assert await sms_opt_out.should_send_soft_stop_gate(db_session, "+14155558888")
    await sms_opt_out.record_soft_stop_gate_sent(db_session, "+14155558888")
    assert not await sms_opt_out.should_send_soft_stop_gate(
        db_session, "+14155558888"
    )
