"""Cascade-notification dedupe keys by membership, not by display name.

`_cascade_rows` (app/services/notification_helpers.py) used to key the
CONTACT_OPTED_OUT/CIRCLE_EMPTIED/CIRCLE_EMPTIED_MID_SESSION dedupe occurrence
by the contact's display name. Since the outbox's dedupe constraint is
global and permanent (ON CONFLICT DO NOTHING on `dedupe_key`, forever), a
name collision silently suppressed a legitimate second notification:

  - two different memberships that happen to share a nickname ("Bob") would
    collide on the SAME owner's cascade.
  - a bare membership id (CONTACT_LEFT's prior fix) still collides across a
    leave -> re-invite -> leave cycle, since `revive_to_pending` reuses the
    same row.

The fix folds `CircleOfTrustMember.updated_at` (bumped by `onupdate` on
every status flip) into the occurrence alongside the membership id, and
applies it to all four cascade kinds via the shared `_cascade_occurrence`
helper.

Related: app/services/notification_helpers.py (_cascade_occurrence,
_cascade_rows), app/services/sms_opt_out.py (OwnerImpact,
compute_owner_impacts), docs/notifications.md (O8/O8b/O9/O10).
"""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token
from app.crud.circle_of_trust import crud_circle_of_trust
from app.crud.phone_number import crud_phone_number
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.notification_delivery import NotificationDelivery, NotificationKind
from app.models.user import User
from app.schemas.circle_of_trust import CircleOfTrustMemberCreate
from app.services import sms_opt_out
from app.services.notification_helpers import (
    _cascade_occurrence,
    fan_out_cascade_notifications,
)
from app.services.sms_opt_out import OwnerImpact
from tests.helpers import create_test_user

pytestmark = pytest.mark.asyncio

# Same pattern as test_circle_cascade_notifications.py /
# test_web_leave_notifies_owner.py: keep the inline send from touching real
# providers.
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


def _cookies(user: User) -> dict:
    return {"access_token": create_access_token(str(user.id))}


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


async def _add_phone_contact(
    db: AsyncSession, owner: User, contact_phone: str, name: str
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


async def _active_member(
    db: AsyncSession,
    inviter: User,
    contact_phone: str,
    *,
    nickname: str,
) -> tuple[User, CircleOfTrustMember]:
    member_user = await create_test_user(db, phone_number=contact_phone)
    row = await crud_circle_of_trust.create_by_phone(
        db,
        user_id=inviter.id,
        obj_in=CircleOfTrustMemberCreate(
            contact_phone_number=member_user.phone_number, nickname=nickname
        ),
    )
    row = await crud_circle_of_trust.accept_invitation(db, contact=row)
    return member_user, row


class TestOptedOutDedupeByMembership:
    async def test_two_members_same_display_name_stop_produce_two_rows(
        self, db_session: AsyncSession
    ) -> None:
        """Two different memberships nicknamed 'Bob' each STOP; a name-only
        occurrence would collide (same owner, same kind, same channel, same
        name) and silently drop the second notification."""
        owner = await create_test_user(db_session, phone_number="+14155599001")
        bob1 = await _add_phone_contact(db_session, owner, "+14155599002", "Bob")
        bob2 = await _add_phone_contact(db_session, owner, "+14155599003", "Bob")
        # A third member keeps remaining_active_count > 0 after each STOP, so
        # both events pick CONTACT_OPTED_OUT rather than CIRCLE_EMPTIED.
        await _add_phone_contact(db_session, owner, "+14155599004", "Carol")
        assert bob1.id != bob2.id

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            phone1, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599002"
            )
            impacts1 = await sms_opt_out.cascade_circle_removal(db_session, phone1)
            await fan_out_cascade_notifications(db_session, impacts1)

            phone2, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599003"
            )
            impacts2 = await sms_opt_out.cascade_circle_removal(db_session, phone2)
            await fan_out_cascade_notifications(db_session, impacts2)

        rows = await _rows_for_owner(
            db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT
        )
        assert len(rows) == 2
        assert len({r.dedupe_key for r in rows}) == 2

    async def test_emptied_kind_keyed_by_membership_too(
        self, db_session: AsyncSession
    ) -> None:
        """An owner's circle is emptied twice by two different memberships
        that happen to share a nickname ('Bob') — the old name-only
        occurrence would collide on the second CIRCLE_EMPTIED."""
        owner = await create_test_user(db_session, phone_number="+14155599010")
        await _add_phone_contact(db_session, owner, "+14155599011", "Bob")

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            phone1, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599011"
            )
            impacts1 = await sms_opt_out.cascade_circle_removal(db_session, phone1)
            assert impacts1[0].remaining_active_count == 0
            await fan_out_cascade_notifications(db_session, impacts1)

            # A brand-new membership (different phone), also nicknamed "Bob",
            # becomes the owner's only member, then leaves too.
            await _add_phone_contact(db_session, owner, "+14155599012", "Bob")
            phone2, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599012"
            )
            impacts2 = await sms_opt_out.cascade_circle_removal(db_session, phone2)
            assert impacts2[0].remaining_active_count == 0
            await fan_out_cascade_notifications(db_session, impacts2)

        rows = await _rows_for_owner(
            db_session, owner.id, NotificationKind.CIRCLE_EMPTIED
        )
        assert len(rows) == 2
        assert len({r.dedupe_key for r in rows}) == 2


class TestLeftDedupeAcrossReinvite:
    async def test_leave_reinvite_leave_produces_two_contact_left_rows(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        inviter = await create_test_user(
            db_session,
            phone_number="+14155599020",
            full_name="Ivy Inviter",
            circle_invite_code="DEDUPE001",
        )
        # A permanent second member keeps remaining_active_count > 0 through
        # both leaves, so the kind stays CONTACT_LEFT (not CIRCLE_EMPTIED).
        await _add_phone_contact(db_session, inviter, "+14155599021", "Carol")
        member_user, row = await _active_member(
            db_session, inviter, "+14155599022", nickname="Bob"
        )

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303

        # Re-invite: the SAME membership row is revived (owner decision —
        # stable identity), then re-accepted.
        row = await crud_circle_of_trust.revive_to_pending(db_session, contact=row)
        row = await crud_circle_of_trust.accept_invitation(db_session, contact=row)

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            resp = await client.post(
                f"/circles/{inviter.circle_invite_code}/leave",
                cookies=_cookies(member_user),
                follow_redirects=False,
            )
        assert resp.status_code == 303

        rows = await _rows_for_owner(
            db_session, inviter.id, NotificationKind.CONTACT_LEFT
        )
        assert len(rows) == 2
        # Distinct dedupe keys, even though both flips are the SAME
        # membership row — the status-change timestamp is what tells them
        # apart (a bare membership id would collide across the cycle).
        assert len({r.dedupe_key for r in rows}) == 2
        for r in rows:
            assert f":{row.id}:" in r.dedupe_key


class TestLeaveIdempotencyKept:
    async def test_repeat_post_of_the_same_leave_produces_one_row(
        self, client: AsyncClient, db_session: AsyncSession
    ) -> None:
        """A re-POST once the membership is already REMOVED is a no-op in
        leave_circle (ACTIVE-only guard) — the new timestamp-based occurrence
        must not turn that guard into a source of duplicate notifications."""
        inviter = await create_test_user(
            db_session,
            phone_number="+14155599030",
            full_name="Ivy Inviter",
            circle_invite_code="DEDUPE002",
        )
        await _add_phone_contact(db_session, inviter, "+14155599031", "Carol")
        member_user, _row = await _active_member(
            db_session, inviter, "+14155599032", nickname="Bob"
        )

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            for _ in range(2):
                resp = await client.post(
                    f"/circles/{inviter.circle_invite_code}/leave",
                    cookies=_cookies(member_user),
                    follow_redirects=False,
                )
                assert resp.status_code == 303

        rows = await _rows_for_owner(
            db_session, inviter.id, NotificationKind.CONTACT_LEFT
        )
        assert len(rows) == 1


class TestStopStartStopRenotifies:
    async def test_second_stop_after_start_notifies_again(
        self, db_session: AsyncSession
    ) -> None:
        """START restores the SAME row to ACTIVE (bumping `updated_at`), so a
        later STOP is a new occurrence — the old name key suppressed it
        forever."""
        owner = await create_test_user(db_session, phone_number="+14155599040")
        await _add_phone_contact(db_session, owner, "+14155599041", "Carol")
        bob = await _add_phone_contact(db_session, owner, "+14155599042", "Bob")

        with _NO_PROVIDERS[0], _NO_PROVIDERS[1]:
            phone, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599042"
            )
            impacts1 = await sms_opt_out.cascade_circle_removal(db_session, phone)
            await fan_out_cascade_notifications(db_session, impacts1)

            await sms_opt_out.record_opt_in(db_session, "+14155599042")
            await db_session.refresh(bob)
            assert bob.status == ContactStatus.ACTIVE

            phone, _ = await crud_phone_number.get_or_create(
                db_session, number="+14155599042"
            )
            impacts2 = await sms_opt_out.cascade_circle_removal(db_session, phone)
            await fan_out_cascade_notifications(db_session, impacts2)

        assert impacts1[0].membership_id == impacts2[0].membership_id == bob.id
        rows = await _rows_for_owner(
            db_session, owner.id, NotificationKind.CONTACT_OPTED_OUT
        )
        assert len(rows) == 2
        assert len({r.dedupe_key for r in rows}) == 2


class TestOccurrenceIsDeterministic:
    async def test_same_instant_in_another_tz_gives_the_same_key(self) -> None:
        """The occurrence normalises to UTC, so the key for one status flip
        doesn't depend on the tz the driver hands back."""
        membership_id = uuid4()
        utc_instant = datetime(2026, 9, 27, 12, 0, 0, 123456, tzinfo=UTC)
        pdt_instant = utc_instant.astimezone(timezone(timedelta(hours=-7)))

        def _occ(at: datetime) -> str:
            return _cascade_occurrence(
                OwnerImpact(
                    owner=None,  # type: ignore[arg-type]  # unused by the key
                    contact_name="Bob",
                    remaining_active_count=1,
                    has_active_session=False,
                    membership_id=membership_id,
                    status_changed_at=at,
                )
            )

        assert _occ(utc_instant) == _occ(utc_instant)
        assert _occ(utc_instant) == _occ(pdt_instant)
        assert _occ(utc_instant) == f"{membership_id}:2026-09-27T12:00:00.123456+00:00"
