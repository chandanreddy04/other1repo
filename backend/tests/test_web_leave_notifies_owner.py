"""POST /circles/{code}/leave notifies the owner (feat brief O8b).

A member who leaves a Circle from the web page now triggers the same owner
cascade notification as the SMS STOP cascade
(`sms_opt_out.cascade_circle_removal` -> `notification_helpers.
fan_out_cascade_notifications`), tagged `reason="left"`:

- others remain in the circle -> CONTACT_LEFT (leave-specific wording,
  "Circle member left" / "{name} left your Circle of Trust. Add someone
  else to replace them.") instead of the STOP cascade's CONTACT_OPTED_OUT.
- the leaving member was the last one, no active session -> CIRCLE_EMPTIED
  (shared with the STOP cascade, unchanged copy).
- the leaving member was the last one during an ACTIVE session ->
  CIRCLE_EMPTIED_MID_SESSION push + SMS (shared with the STOP cascade,
  unchanged copy).

Also pins: the STOP cascade itself is untouched (still CONTACT_OPTED_OUT
with its own body), declining a PENDING invite is not a "leave" and never
notifies, and a notification failure never blocks the leave redirect.

Related: app/services/circle_invitations.py (leave_circle),
app/services/sms_opt_out.py (compute_owner_impacts, cascade_circle_removal),
app/services/notification_helpers.py (fan_out_cascade_notifications,
_cascade_kind), app/web/routes_web.py (circle_invite_leave),
docs/notifications.md (O8b).
"""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import (
    DeliveryChannel,
    NotificationDelivery,
    NotificationKind,
)
from app.models.session import Session, SessionStatus, SessionType
from app.models.user import User
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from app.services import sms_opt_out
from app.services.notification_helpers import fan_out_cascade_notifications
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio


def _cookies(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


# The cascade enqueues delivery rows the reconciler dispatches; these patches
# keep the inline send from touching real providers (same pattern as
# test_circle_cascade_notifications.py).
_NO_PROVIDERS = (
    patch(
        "app.services.notification_outbox.ExpoPushNotificationService.send_notification",
        new_callable=AsyncMock,
        return_value={"ok_tokens": [], "dead_tokens": [], "ticket_ids": {}},
    ),
    patch(
        "app.services.notification_outbox.sms_opt_out.gated_send_sms",
        new_callable=AsyncMock,
        return_value=None,
    ),
)


async def _active_member(
    db: AsyncSession,
    inviter_phone: str,
    contact_phone: str,
    *,
    code: str,
    nickname: str = "Bob",
) -> tuple[User, User, CircleOfTrustMember]:
    """An inviter with one ACTIVE member, named deterministically via
    nickname so the notification body is exact-matchable."""
    inviter = await create_test_user(
        db, phone_number=inviter_phone, full_name="Ivy Inviter", circle_invite_code=code
    )
    member_user = await create_test_user(
        db, phone_number=contact_phone, full_name="Cody Contact"
    )
    row = await crud_circle_of_trust.create_by_phone(
        db,
        user_id=inviter.id,
        obj_in=CircleOfTrustMemberCreate(
            contact_phone_number=member_user.phone_number, nickname=nickname
        ),
    )
    row = await crud_circle_of_trust.accept_invitation(db, contact=row)
    return inviter, member_user, row


async def _rows_for_owner(
    db: AsyncSession, owner_id, kind: NotificationKind
) -> list[NotificationDelivery]:
    return list(
        (
            await db.execute(
                select(NotificationDelivery).where(
                    NotificationDelivery.recipient_user_id == owner_id,
                    NotificationDelivery.kind == kind,
                )
            )
        )
        .scalars()
        .all()
    )


async def _status_of(db: AsyncSession, member_id) -> ContactStatus:
    """Fresh column read of a membership's status — no ORM instance, so it
    works after leave_circle's rollback has expired the session's objects."""
    return (
        await db.execute(
            select(CircleOfTrustMember.status).where(
                CircleOfTrustMember.id == member_id
            )
        )
    ).scalar_one()


class TestLeaveWithOthersRemaining:
    async def test_leave_enqueues_one_contact_left_push_with_exact_body(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inviter, member_user, _row = await _active_member(
            db_session, "+14155598101", "+14155598102", code="LEAVEN001"
        )
        # A second ACTIVE member in the SAME circle so the departing member
        # leaves someone else behind.
        other = await create_test_user(db_session, phone_number="+14155598103")
        other_row = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=other.phone_number, nickname="Carol"
            ),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=other_row)

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303

        rows = await _rows_for_owner(db_session, inviter.id, NotificationKind.CONTACT_LEFT)
        assert len(rows) == 1
        assert rows[0].channel == DeliveryChannel.PUSH
        assert rows[0].title == "Circle member left"
        assert rows[0].body == (
            "Bob left your Circle of Trust. Add someone else to replace them."
        )
        assert not await _rows_for_owner(
            db_session, inviter.id, NotificationKind.CONTACT_OPTED_OUT
        )


class TestLeaveAsLastMember:
    async def test_leave_as_last_member_no_session_enqueues_circle_emptied(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inviter, member_user, _row = await _active_member(
            db_session, "+14155598110", "+14155598111", code="LEAVEE001"
        )
        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        rows = await _rows_for_owner(db_session, inviter.id, NotificationKind.CIRCLE_EMPTIED)
        assert len(rows) == 1
        assert rows[0].channel == DeliveryChannel.PUSH
        assert rows[0].body == (
            "Bob left your Circle of Trust, and they were the last member. "
            "Add someone to alert on your next session."
        )
        assert not await _rows_for_owner(
            db_session, inviter.id, NotificationKind.CONTACT_LEFT
        )

    async def test_leave_as_last_member_mid_session_enqueues_push_and_sms(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        from datetime import UTC, datetime, timedelta

        inviter, member_user, _row = await _active_member(
            db_session, "+14155598120", "+14155598121", code="LEAVEM001"
        )
        session = Session(
            user_id=inviter.id,
            session_type=SessionType.CHECKIN.value,
            expected_return_time=datetime.now(UTC) + timedelta(hours=1),
            status=SessionStatus.ACTIVE.value,
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        rows = list(
            (
                await db_session.execute(
                    select(NotificationDelivery).where(
                        NotificationDelivery.session_id == session.id,
                        NotificationDelivery.kind
                        == NotificationKind.CIRCLE_EMPTIED_MID_SESSION,
                    )
                )
            )
            .scalars()
            .all()
        )
        assert {r.channel for r in rows} == {DeliveryChannel.PUSH, DeliveryChannel.SMS}
        push = next(r for r in rows if r.channel == DeliveryChannel.PUSH)
        assert push.body == (
            "Bob left your Circle of Trust and they were the last member of "
            "your Circle. Check in on time \u2014 no one will be alerted if you miss it."
        )


class TestStopCascadeUnchanged:
    async def test_stop_cascade_still_uses_contact_opted_out(
        self, db_session: AsyncSession
    ) -> None:
        """The STOP path (reason defaults to "opted_out") is untouched by
        the new leave-reason plumbing: still CONTACT_OPTED_OUT with its own
        (unchanged) body."""
        owner = await create_test_user(db_session, phone_number="+14155598130")
        contact_phone, _ = await crud_phone_number.get_or_create(
            db_session, number="+14155598131"
        )
        m = CircleOfTrustMember(
            user_id=owner.id,
            nickname="Bob",
            contact_phone_number_id=contact_phone.id,
            status=ContactStatus.ACTIVE,
        )
        db_session.add(m)
        # A second ACTIVE member so the cascade leaves the owner non-empty.
        other_phone, _ = await crud_phone_number.get_or_create(
            db_session, number="+14155598132"
        )
        db_session.add(
            CircleOfTrustMember(
                user_id=owner.id,
                nickname="Carol",
                contact_phone_number_id=other_phone.id,
                status=ContactStatus.ACTIVE,
            )
        )
        await db_session.commit()

        impacts = await sms_opt_out.cascade_circle_removal(db_session, contact_phone)
        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            await fan_out_cascade_notifications(db_session, impacts)

        rows = await _rows_for_owner(db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT)
        assert len(rows) == 1
        assert rows[0].body == (
            "Bob asked us to stop texting them, so we removed them from your "
            "Circle of Trust. Add someone else to replace them."
        )


class TestDeclineIsNotALeave:
    async def test_declining_a_pending_invite_does_not_notify(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inviter = await create_test_user(
            db_session,
            phone_number="+14155598140",
            full_name="Ivy Inviter",
            circle_invite_code="LEAVED001",
        )
        decliner = await create_test_user(db_session, phone_number="+14155598141")
        await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=decliner.phone_number, nickname="Bob"
            ),
        )
        resp = await client.post(
            f"/circles/{inviter.circle_invite_code}/decline",
            cookies=_cookies(decliner),
            follow_redirects=False,
        )
        assert resp.status_code == 303
        for kind in (
            NotificationKind.CONTACT_LEFT,
            NotificationKind.CONTACT_OPTED_OUT,
            NotificationKind.CIRCLE_EMPTIED,
            NotificationKind.CIRCLE_EMPTIED_MID_SESSION,
        ):
            assert not await _rows_for_owner(db_session, inviter.id, kind)


class TestNotificationFailureDoesNotBlockLeave:
    async def test_leave_redirect_survives_a_notification_failure(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inviter, member_user, row = await _active_member(
            db_session, "+14155598150", "+14155598151", code="LEAVEF001"
        )
        row_id = row.id
        with patch(
            "app.services.sms_opt_out.compute_owner_impacts",
            new=AsyncMock(side_effect=RuntimeError("db blip")),
        ):
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles"

        # leave_circle rolls back the failed fan-out, which expires every
        # instance in the (shared, in tests) session — re-load by id.
        assert await _status_of(db_session, row_id) == ContactStatus.REMOVED


class TestLeaveIsIdempotent:
    async def test_second_leave_post_does_not_notify_twice(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A re-POST once the membership is already REMOVED is a no-op in
        leave_circle (ACTIVE-only guard), so the owner gets exactly one
        CONTACT_LEFT push; the membership-id + status-change-timestamp
        occurrence in the dedupe key is the backstop."""
        inviter, member_user, row = await _active_member(
            db_session, "+14155598160", "+14155598161", code="LEAVEI001"
        )
        other = await create_test_user(db_session, phone_number="+14155598162")
        other_row = await crud_circle_of_trust.create_by_phone(
            db_session,
            user_id=inviter.id,
            obj_in=CircleOfTrustMemberCreate(
                contact_phone_number=other.phone_number, nickname="Carol"
            ),
        )
        await crud_circle_of_trust.accept_invitation(db_session, contact=other_row)

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            for _ in range(2):
                resp = await client.post(
                    f"/circles/{inviter.circle_invite_code}/leave",
                    cookies=_cookies(member_user),
                    follow_redirects=False,
                )
                assert resp.status_code == 303

        rows = await _rows_for_owner(db_session, inviter.id, NotificationKind.CONTACT_LEFT)
        assert len(rows) == 1
        assert f":{row.id}:" in rows[0].dedupe_key


class TestFailedEnqueueDoesNotPoisonTheSession:
    async def test_db_error_mid_fan_out_rolls_back_and_keeps_the_leave(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A DB error INSIDE the fan-out's transaction (the enqueue insert)
        aborts that transaction. leave_circle must roll it back so the
        request's session stays usable, while the leave itself — committed
        before notification — survives."""
        from sqlalchemy import text

        inviter, member_user, row = await _active_member(
            db_session, "+14155598170", "+14155598171", code="LEAVEP001"
        )
        row_id, inviter_id = row.id, inviter.id

        async def _failing_enqueue(db: AsyncSession, **_kwargs: object) -> int:
            await db.execute(text("SELECT 1/0"))
            return 0

        with patch(
            "app.services.notification_outbox.crud_nd.enqueue",
            new=_failing_enqueue,
        ):
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/circles"

        # The session is usable again (no aborted transaction left behind)
        # and the leave committed before the fan-out is intact.
        assert await _status_of(db_session, row_id) == ContactStatus.REMOVED
        assert not await _rows_for_owner(
            db_session, inviter_id, NotificationKind.CIRCLE_EMPTIED
        )
