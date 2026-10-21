"""Pins the copy the owner reviewed and approved 2026-09-26/27 (the
copy-batch final-strings review) — the copy freeze (and test_vocabulary.py's
ALLOWED / BACKEND_ALLOWED entries) is lifted for exactly these strings. Every
expected value here is a LITERAL copied from the approved final-strings list,
never an import compared with itself.

Covers: the byte-exact literal constants that changed in
notification_constants.py, O7 contact-unreachable name resolution + title,
O11 {started_at} local-time rendering (and its time-free no-offset body),
the soft-stop gate's new name-vs-count
branching (cases A and D), the M6 acknowledgement fallback when an owner has
no full_name, the O15 group-plan-grace fallback ("The owner", never split),
the M5 all-clear single-line SMS, the O16 lapse SMS/push-title variants, and
the U1/U2/U4/U7/U8 prefilled texts in the mobile source.

Related: app/services/notification_constants.py, app/services/
notification_helpers.py, app/services/notification_outbox.py, app/services/
alert_acknowledgement.py, app/services/group_plan_service.py, app/services/
sub_lapse_notifications.py, docs/notifications.md.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud_nd
from app.crud.phone_number import crud_phone_number
from app.models.alert import Alert, AlertStatus, AlertType
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from app.services import (
    group_plan_service,
    notification_constants,
    notification_outbox,
    sub_lapse_notifications,
)
from app.services.alert_acknowledgement import acknowledge_alert
from app.services.notification_constants import (
    GROUP_PLAN_GRACE_BODY,
    SOFT_STOP_GATE_ACCOUNT_AND_CONTACT,
    SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE,
    SOFT_STOP_GATE_MULTI_OWNER,
    SOFT_STOP_GATE_SINGLE_OWNER,
)
from app.services.notification_helpers import (
    _data_deleted_body,
    _format_started_at,
    render_soft_stop_gate,
    send_all_clear_to_circle,
)
from app.services.sms import SMSProvider, SMSResult
from app.services.sms_opt_out import SenderProfile
from app.services.sub_lapse_notifications import SUB_SHORT_URL, Moment
from tests.helpers import create_test_subscription, create_test_user

pytestmark = pytest.mark.asyncio

_PHONE = iter(f"+14155598{n:03d}" for n in range(0, 999))


def _next_phone() -> str:
    return next(_PHONE)


# ---------------------------------------------------------------------------
# A. Byte-exact literal copy (one assertion per changed constant).
# ---------------------------------------------------------------------------

_EXPECTED_LITERAL_COPY: dict[str, str] = {
    "SESSION_EXPIRED_TITLE": "⚠️ You missed your check-in",
    "SESSION_EXPIRED_BODY": "We're alerting your Circle. Mark yourself safe if you're okay.",
    "CONTACT_UNREACHABLE_TITLE": "Couldn't reach a Circle member",
    "CONTACT_UNREACHABLE_BODY": (
        "We couldn't reach {name} about your session. "
        "Try calling or texting them directly."
    ),
    "CONTACT_OPTED_OUT_TITLE": "Circle member unsubscribed",
    "CONTACT_OPTED_OUT_BODY": (
        "{name} asked us to stop texting them, so we removed them from "
        "your Circle of Trust. Add someone else to replace them."
    ),
    "CIRCLE_EMPTIED_TITLE": "Your Circle of Trust is empty",
    "CIRCLE_EMPTIED_BODY": (
        "{name} left your Circle of Trust, and they were the last member. "
        "Add someone to alert on your next session."
    ),
    "CIRCLE_EMPTIED_MID_SESSION_TITLE": "Your Circle of Trust is empty",
    "CIRCLE_EMPTIED_MID_SESSION_BODY": (
        "{name} left your Circle of Trust and they were the last member "
        "of your Circle. Check in on time — no one will be alerted if "
        "you miss it."
    ),
    "DATA_DELETED_TITLE": "Session data deleted",
    "DATA_DELETED_BODY": (
        "Your {started_at} session's location history and photo have been "
        "automatically deleted."
    ),
    "DATA_DELETED_BODY_NO_TIME": (
        "Your session's location history and photo have been automatically "
        "deleted."
    ),
    "ALERT_ACKNOWLEDGED_MEMBER_BODY_NO_NAME": (
        "Made It Home: Your contact's alert was acknowledged."
    ),
    "ACCOUNT_HOLDER_STOPPED_BODY": (
        "Texts are off — including your sign-in codes and alerts about "
        "people whose Circle you're in. Tap to manage."
    ),
    "GROUP_PLAN_GRACE_TITLE": "Your Group Plan has ended",
    "GROUP_PLAN_GRACE_BODY": (
        "{owner}'s Group Plan ended, so your access ends in {days} days. "
        "Subscribe to keep using Made It Home."
    ),
    "ALL_CLEAR_SMS": "✅ All clear: {name} checked in and marked themselves safe.",
    "ALERT_MISSED_BODY": (
        "Made It Home: {name} hasn't checked in and expected to be back by "
        "{time}. Please check on them: {phone}."
    ),
    "CIRCLE_WELCOME_SMS": (
        "Made It Home: You're now in {inviter_name}'s Circle of Trust. "
        "We'll text you only if they need help — save this number so "
        "alerts reach you. Reply STOP to opt out; that also removes you "
        "from their Circle."
    ),
    "SOFT_STOP_GATE_SINGLE_OWNER": (
        "Made It Home: We can stop texting you, but that would also remove "
        "you from {name}'s Circle of Trust — you wouldn't be alerted if "
        "they need help. Reply STOP to confirm, or ignore this to stay."
    ),
    "SOFT_STOP_GATE_MULTI_OWNER": (
        "Made It Home: We can stop texting you, but that would also remove "
        "you from {count} people's Circles of Trust. You will not be "
        "alerted if they need help. Reply STOP to confirm, or ignore "
        "this to stay."
    ),
    "SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE": (
        "Made It Home: We can stop texting you, but that would also remove "
        "you from {name}'s Circle of Trust AND stop your account sign-in "
        "codes. Reply STOP to confirm, or ignore this to stay."
    ),
    "SOFT_STOP_GATE_ACCOUNT_AND_CONTACT": (
        "Made It Home: We can stop texting you, but that would also remove "
        "you from {count} people's Circles of Trust AND stop your "
        "account sign-in codes. Reply STOP to confirm, or ignore this to stay."
    ),
}


@pytest.mark.parametrize(
    "name,expected", sorted(_EXPECTED_LITERAL_COPY.items())
)
async def test_reviewed_constant_is_byte_exact(name: str, expected: str) -> None:
    assert getattr(notification_constants, name) == expected


# ---------------------------------------------------------------------------
# B. O11 — {started_at} local-time rendering.
# ---------------------------------------------------------------------------


async def test_started_at_renders_local_with_offset() -> None:
    session = SimpleNamespace(
        created_at=datetime(2026, 9, 23, 4, 40, tzinfo=UTC),
        tz_offset_minutes=-420,  # PDT
    )
    assert _format_started_at(session) == "Sep 22 · 9:40 PM"


async def test_no_offset_sends_time_free_body_never_utc() -> None:
    """No tz_offset_minutes → no timestamp at all (a UTC clock time is never
    rendered): the O11 body falls back to DATA_DELETED_BODY_NO_TIME."""
    session = SimpleNamespace(
        created_at=datetime(2026, 9, 23, 4, 40, tzinfo=UTC),
        tz_offset_minutes=None,
    )
    assert _format_started_at(session) is None
    assert _data_deleted_body(session) == (
        "Your session's location history and photo have been automatically "
        "deleted."
    )


async def test_offset_body_names_local_start_time() -> None:
    session = SimpleNamespace(
        created_at=datetime(2026, 9, 23, 4, 40, tzinfo=UTC),
        tz_offset_minutes=-420,  # PDT
    )
    assert _data_deleted_body(session) == (
        "Your Sep 22 · 9:40 PM session's location history and photo have "
        "been automatically deleted."
    )


async def test_started_at_unpadded_day_and_positive_offset() -> None:
    """No zero-padding on day or hour; a positive offset (east of UTC) can
    roll the local date forward."""
    session = SimpleNamespace(
        created_at=datetime(2026, 9, 4, 21, 5, tzinfo=UTC),
        tz_offset_minutes=330,  # IST, +5:30
    )
    assert _format_started_at(session) == "Sep 5 · 2:35 AM"


# ---------------------------------------------------------------------------
# C. O7 — contact-unreachable name resolution + title.
# ---------------------------------------------------------------------------


async def test_contact_unreachable_resolves_membership_display_name(
    db_session: AsyncSession,
) -> None:
    owner = await create_test_user(db_session, phone_number=_next_phone())
    contact_phone, _ = await crud_phone_number.get_or_create(
        db_session, number=_next_phone()
    )
    member = CircleOfTrustMember(
        user_id=owner.id,
        nickname="Bestie",
        contact_phone_number_id=contact_phone.id,
        status=ContactStatus.ACTIVE.value,
    )
    db_session.add(member)
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    now = datetime.now(UTC)
    await crud_nd.enqueue(
        db_session,
        rows=[
            DeliveryDraft(
                dedupe_key=f"ca-{session.id}",
                kind=NotificationKind.CIRCLE_ALERT,
                channel=DeliveryChannel.SMS,
                body="hi",
                next_attempt_at=now,
                recipient_phone_id=contact_phone.id,
                session_id=session.id,
            )
        ],
    )
    [refused] = (
        (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.dedupe_key == f"ca-{session.id}"
                )
            )
        )
        .scalars()
        .all()
    )

    await notification_outbox._escalate_unreachable(db_session, refused, now)

    rows = (
        (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.kind == NotificationKind.CONTACT_UNREACHABLE,
                    NotificationDelivery.recipient_user_id == owner.id,
                )
            )
        )
        .scalars()
        .all()
    )
    by_channel = {r.channel: r for r in rows}
    expected_body = (
        "We couldn't reach Bestie about your session. "
        "Try calling or texting them directly."
    )
    assert by_channel[DeliveryChannel.PUSH].title == "Couldn't reach a Circle member"
    assert by_channel[DeliveryChannel.PUSH].body == expected_body
    assert (
        by_channel[DeliveryChannel.SMS].body
        == f"Couldn't reach a Circle member\n{expected_body}"
    )
    # The old copy embedded the contact's raw phone number — never again.
    assert contact_phone.number not in by_channel[DeliveryChannel.SMS].body


async def test_contact_unreachable_falls_back_without_a_membership(
    db_session: AsyncSession,
) -> None:
    """A refused delivery whose phone id has no matching CircleOfTrustMember
    row (orphaned data) still gets an honest, generic name."""
    owner = await create_test_user(db_session, phone_number=_next_phone())
    orphan_phone, _ = await crud_phone_number.get_or_create(
        db_session, number=_next_phone()
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    now = datetime.now(UTC)
    await crud_nd.enqueue(
        db_session,
        rows=[
            DeliveryDraft(
                dedupe_key=f"ca-orphan-{session.id}",
                kind=NotificationKind.CIRCLE_ALERT,
                channel=DeliveryChannel.SMS,
                body="hi",
                next_attempt_at=now,
                recipient_phone_id=orphan_phone.id,
                session_id=session.id,
            )
        ],
    )
    [refused] = (
        (
            await db_session.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.dedupe_key == f"ca-orphan-{session.id}"
                )
            )
        )
        .scalars()
        .all()
    )

    await notification_outbox._escalate_unreachable(db_session, refused, now)

    row = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.kind == NotificationKind.CONTACT_UNREACHABLE,
                NotificationDelivery.channel == DeliveryChannel.PUSH,
            )
        )
    ).scalar_one()
    assert row.body == (
        "We couldn't reach a Circle member about your session. "
        "Try calling or texting them directly."
    )


# ---------------------------------------------------------------------------
# D. Soft-stop gate name-vs-count branching (cases A and D).
# ---------------------------------------------------------------------------


async def test_gate_a_single_owner_names_them() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=["Priya"], owner_count=1, has_account=False)
    )
    assert body == SOFT_STOP_GATE_SINGLE_OWNER.format(name="Priya")
    assert "Priya" in body


async def test_gate_a_nameless_owner_reads_possessively() -> None:
    """get_sender_profile's fallback for an owner with no full_name is
    "someone" — it must read grammatically inside "{name}'s Circle"."""
    body = render_soft_stop_gate(
        SenderProfile(owner_names=["someone"], owner_count=1, has_account=False)
    )
    assert "remove you from someone's Circle of Trust —" in body


async def test_gate_b_multi_owner_still_uses_count() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=[], owner_count=3, has_account=False)
    )
    assert body == SOFT_STOP_GATE_MULTI_OWNER.format(count=3)


async def test_gate_d_count_one_names_the_owner() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=["Priya"], owner_count=1, has_account=True)
    )
    assert body == SOFT_STOP_GATE_ACCOUNT_AND_CONTACT_SINGLE.format(name="Priya")
    assert "Priya" in body


async def test_gate_d_count_two_uses_count_wording() -> None:
    body = render_soft_stop_gate(
        SenderProfile(owner_names=[], owner_count=2, has_account=True)
    )
    assert body == SOFT_STOP_GATE_ACCOUNT_AND_CONTACT.format(count=2)
    assert "2 people" in body


# ---------------------------------------------------------------------------
# E. M6 — acknowledgement-broadcast fallback when the owner has no full_name.
# ---------------------------------------------------------------------------


async def test_m6_fallback_body_when_owner_has_no_full_name(
    db_session: AsyncSession,
) -> None:
    owner = await create_test_user(
        db_session, phone_number=_next_phone(), full_name=None
    )
    acker = await create_test_user(db_session, phone_number=_next_phone())
    other = await create_test_user(db_session, phone_number=_next_phone())
    db_session.add_all(
        [
            CircleOfTrustMember(
                user_id=owner.id,
                contact_phone_number_id=acker.phone_number_id,
                nickname="Acker",
                status=ContactStatus.ACTIVE.value,
            ),
            CircleOfTrustMember(
                user_id=owner.id,
                contact_phone_number_id=other.phone_number_id,
                nickname="Other",
                status=ContactStatus.ACTIVE.value,
            ),
        ]
    )
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=30),
        status=SessionStatus.MISSED.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(session)

    alert = Alert(
        session_id=session.id,
        sent_to_user_id=acker.id,
        alert_type=AlertType.MISSED_SESSION,
        status=AlertStatus.SENT,
        sent_at=datetime.now(UTC),
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)

    await acknowledge_alert(db_session, alert=alert)

    row = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.kind == NotificationKind.ALERT_ACKNOWLEDGED,
                NotificationDelivery.recipient_phone_id == other.phone_number_id,
            )
        )
    ).scalar_one()
    assert row.body == "Made It Home: Your contact's alert was acknowledged."


# ---------------------------------------------------------------------------
# F. O15 — group-plan-grace fallback is "The owner", never split.
# ---------------------------------------------------------------------------


async def test_o15_fallback_is_the_owner_not_split(db_session: AsyncSession) -> None:
    owner = await create_test_user(
        db_session, phone_number=_next_phone(), full_name=None
    )
    sub = await create_test_subscription(db_session, owner, plan_type="group_monthly")
    plan = await group_plan_service.create_group_plan(
        db_session, owner=owner, subscription_id=sub.id
    )
    member = await create_test_user(
        db_session,
        phone_number=_next_phone(),
        expo_push_token="ExponentPushToken[o15member]",
    )
    await group_plan_service.join_plan(
        db_session, user=member, invite_code=plan.invite_code
    )

    with patch(
        "app.services.notification_outbox.ExpoPushNotificationService"
    ) as mock_push_cls:
        mock_push_cls.send_notification = AsyncMock(
            return_value={
                "ok_tokens": [member.expo_push_token],
                "dead_tokens": [],
                "ticket_ids": {member.expo_push_token: "ticket-o15"},
            }
        )
        await group_plan_service.grant_grace_period_to_members(db_session, plan, days=7)

    row = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.kind == NotificationKind.GROUP_PLAN_GRACE,
                NotificationDelivery.recipient_user_id == member.id,
            )
        )
    ).scalar_one()
    # Never "The" (the old bug: splitting "The owner" on the first word).
    assert row.body == GROUP_PLAN_GRACE_BODY.format(owner="The owner", days=7)
    assert "The owner's Group Plan ended" in row.body


# ---------------------------------------------------------------------------
# G. M5 — all-clear SMS is one merged line, not TITLE + "\n" + BODY.
# ---------------------------------------------------------------------------


async def test_all_clear_sms_is_a_single_line(db_session: AsyncSession) -> None:
    owner = await create_test_user(
        db_session, phone_number=_next_phone(), full_name="Sasha Safe"
    )
    contact = await create_test_user(db_session, phone_number=_next_phone())
    member = CircleOfTrustMember(
        user_id=owner.id,
        contact_phone_number_id=contact.phone_number_id,
        status=ContactStatus.ACTIVE.value,
    )
    db_session.add(member)
    session = Session(
        user_id=owner.id,
        expected_return_time=datetime.now(UTC) - timedelta(minutes=5),
        status=SessionStatus.MISSED.value,
    )
    db_session.add(session)
    await db_session.commit()
    await db_session.refresh(member)
    await db_session.refresh(session)

    with patch(
        "app.services.notification_outbox.sms_opt_out.gated_send_sms",
        new=AsyncMock(
            return_value=SMSResult(
                success=True, message_id="sm_allclear", provider=SMSProvider.TWILIO
            )
        ),
    ):
        await send_all_clear_to_circle(db_session, [member], owner, session)

    row = (
        await db_session.execute(
            select(NotificationDelivery).where(
                NotificationDelivery.kind == NotificationKind.ALL_CLEAR,
                NotificationDelivery.session_id == session.id,
            )
        )
    ).scalar_one()
    assert row.body == "✅ All clear: Sasha Safe checked in and marked themselves safe."
    assert "\n" not in row.body


# ---------------------------------------------------------------------------
# H. O16 — lapse SMS variants ("Group Plan", "access") and per-moment push
# titles. The URL is unchanged (frozen "forever"), so it's composed from
# SUB_SHORT_URL rather than restated.
# ---------------------------------------------------------------------------

_EXPECTED_GROUP_SMS = {
    Moment.T_ZERO: "Your Group Plan from {owner_name} ends {date}. "
    "Subscribe to keep access: ",
    Moment.T_MINUS_7D: "Your Group Plan ends in 7 days. Subscribe now to avoid a gap: ",
    Moment.T_MINUS_1D: "Last day: Your Group Plan ends tomorrow. "
    "Subscribe to keep access: ",
    Moment.T_END: "Your Made It Home Group Plan ended today. Subscribe to continue: ",
}
_EXPECTED_SPONSOR_SMS = {
    Moment.T_ZERO: "Your sponsorship from {sponsor_phone_full} ends {date}. "
    "Subscribe to keep access: ",
    Moment.T_MINUS_7D: "Your sponsorship ends in 7 days. "
    "Subscribe now to avoid a gap: ",
    Moment.T_MINUS_1D: "Last day: Your sponsorship ends tomorrow. "
    "Subscribe to keep access: ",
    Moment.T_END: "Your Made It Home sponsorship ended today. Subscribe to continue: ",
}
_EXPECTED_PUSH_TITLE = {
    Moment.T_ZERO: "Your access is ending",
    Moment.T_MINUS_7D: "Your access is ending",
    Moment.T_MINUS_1D: "Your access is ending",
    Moment.T_END: "Your access has ended",
}


@pytest.mark.parametrize("moment", list(Moment))
async def test_o16_lapse_copy_is_byte_exact(moment: Moment) -> None:
    assert sub_lapse_notifications._GROUP_SMS[moment] == (
        _EXPECTED_GROUP_SMS[moment] + SUB_SHORT_URL
    )
    assert sub_lapse_notifications._SPONSOR_SMS[moment] == (
        _EXPECTED_SPONSOR_SMS[moment] + SUB_SHORT_URL
    )
    assert sub_lapse_notifications._PUSH_TITLE[moment] == _EXPECTED_PUSH_TITLE[moment]


async def test_o16_short_url_is_unchanged() -> None:
    assert SUB_SHORT_URL.endswith("/sub")


# ---------------------------------------------------------------------------
# I. U1/U2/U4/U7/U8 — prefilled texts, pinned in the mobile source (the
# {link} composition — runtime short domain + /c/, /g/, /s/ — included).
# ---------------------------------------------------------------------------

_REPO = Path(__file__).resolve().parents[2]

_EXPECTED_PREFILLS = [
    (
        "mobile/hooks/useCircleScreen.ts",
        "`Hey! Can you join my Circle of Trust on Made It Home? I check in when "
        "I'm out — if I miss one, it texts you. Accept here: ${inviteUrl}`",
    ),
    (
        "mobile/hooks/useCircleScreen.ts",
        "`Hey! Still hoping you'll join my Circle of Trust — it takes a few "
        "seconds to accept: ${inviteUrl}`",
    ),
    (
        "mobile/hooks/useCircleScreen.ts",
        "const inviteUrl = `${getAppConfigSnapshot().shortDomain}/c/"
        "${user.circle_invite_code}`",
    ),
    (
        "mobile/components/CircleMemberCard.tsx",
        "`Hey, can you text START to ${smsNumber}? I'd like to keep you in my "
        "Circle of Trust on Made It Home.`",
    ),
    (
        "mobile/components/subscription/GroupState.tsx",
        "`Join my Group Plan on Made It Home: "
        "${appConfig.shortDomain}/g/${plan.invite_code}`",
    ),
    (
        "mobile/app/sponsorship-requests/new.tsx",
        "`Hey! I've been using Made It Home — a safety app that alerts my Circle "
        "if I miss a check-in. Would you sponsor my subscription? ${giftUrl}`",
    ),
    (
        "mobile/app/sponsorship-requests/new.tsx",
        "const giftUrl = `${appConfig.shortDomain}/s/${user?.share_code}`",
    ),
]


@pytest.mark.parametrize("path,literal", _EXPECTED_PREFILLS)
async def test_prefilled_text_is_byte_exact(path: str, literal: str) -> None:
    assert literal in (_REPO / path).read_text(encoding="utf-8")
