"""Outbox CRUD: idempotent enqueue, the reconciler due-scan, and the state
transitions (backoff -> exhausted, sent, delivered, superseded, expiry).

Related: app/crud/notification_delivery.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import DeliveryDraft
from app.crud.notification_delivery import (
    crud_notification_delivery as crud,
)
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationKind,
)
from app.models.session import Session, SessionStatus
from tests.helpers import create_test_user

NOW = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)


def _draft(
    user,
    *,
    key,
    kind=NotificationKind.CIRCLE_ALERT,
    channel=DeliveryChannel.SMS,
    next_attempt_at=NOW,
    expires_at=None,
    session_id=None,
) -> DeliveryDraft:
    return DeliveryDraft(
        dedupe_key=key,
        kind=kind,
        channel=channel,
        body="b",
        next_attempt_at=next_attempt_at,
        # Circle kinds are SMS-only (owner decision): SMS to the phone.
        recipient_phone_id=user.phone_number_id,
        expires_at=expires_at,
        session_id=session_id,
    )


async def _session(db, user) -> Session:
    s = Session(
        user_id=user.id,
        expected_return_time=NOW,
        status=SessionStatus.ACTIVE.value,
    )
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest.mark.asyncio
class TestEnqueue:
    async def test_inserts_and_is_idempotent(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155591001")
        assert await crud.enqueue(db_session, rows=[_draft(user, key="k1")]) == 1
        # Same dedupe_key → no-op.
        assert await crud.enqueue(db_session, rows=[_draft(user, key="k1")]) == 0

    async def test_empty_rows(self, db_session: AsyncSession):
        assert await crud.enqueue(db_session, rows=[]) == 0


@pytest.mark.asyncio
class TestGetDue:
    async def test_excludes_future_and_expired(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155591002")
        await crud.enqueue(
            db_session,
            rows=[
                _draft(user, key="due", next_attempt_at=NOW - timedelta(minutes=1)),
                _draft(user, key="future", next_attempt_at=NOW + timedelta(minutes=5)),
                _draft(
                    user,
                    key="expired",
                    next_attempt_at=NOW - timedelta(minutes=1),
                    expires_at=NOW - timedelta(seconds=1),
                ),
            ],
        )
        keys = {d.dedupe_key for d in await crud.get_due(db_session, now=NOW)}
        assert keys == {"due"}

    async def test_excludes_terminal(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155591003")
        await crud.enqueue(
            db_session,
            rows=[_draft(user, key="t", next_attempt_at=NOW - timedelta(minutes=1))],
        )
        [d] = await crud.get_due(db_session, now=NOW)
        await crud.mark_delivered(db_session, delivery=d, now=NOW)
        assert all(
            x.dedupe_key != "t" for x in await crud.get_due(db_session, now=NOW)
        )


@pytest.mark.asyncio
class TestTransitions:
    async def test_backoff_then_exhaust(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155591004")
        await crud.enqueue(
            db_session,
            rows=[_draft(user, key="f", next_attempt_at=NOW - timedelta(minutes=1))],
        )
        [d] = await crud.get_due(db_session, now=NOW)

        await crud.mark_failed_with_backoff(
            db_session, delivery=d, backoff_seconds=(60,), max_attempts=2, now=NOW
        )
        assert d.status == DeliveryStatus.FAILED
        assert d.attempt_count == 1
        assert d.next_attempt_at == NOW + timedelta(seconds=60)

        await crud.mark_failed_with_backoff(
            db_session, delivery=d, backoff_seconds=(60,), max_attempts=2, now=NOW
        )
        assert d.status == DeliveryStatus.EXHAUSTED
        assert d.attempt_count == 2

    async def test_mark_sent_sets_provider_and_increments(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155591005")
        await crud.enqueue(db_session, rows=[_draft(user, key="s")])
        [d] = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session,
            delivery=d,
            provider="twilio",
            provider_message_id="tid-1",
            now=NOW,
        )
        assert d.status == DeliveryStatus.SENT
        assert d.provider_message_id == "tid-1"
        assert d.attempt_count == 1
        assert (
            await crud.get_by_provider_message_id(db_session, "tid-1")
        ).dedupe_key == "s"


@pytest.mark.asyncio
class TestSupersedeCountExpire:
    async def test_supersede_non_terminal_session_kind(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155591006")
        s = await _session(db_session, user)
        await crud.enqueue(
            db_session,
            rows=[
                _draft(
                    user,
                    key="rn1",
                    kind=NotificationKind.CIRCLE_RENUDGE,
                    session_id=s.id,
                ),
                _draft(
                    user,
                    key="rn2",
                    kind=NotificationKind.CIRCLE_RENUDGE,
                    session_id=s.id,
                ),
            ],
        )
        n = await crud.supersede(
            db_session, session_id=s.id, kind=NotificationKind.CIRCLE_RENUDGE, now=NOW
        )
        assert n == 2
        assert not await crud.get_due(db_session, now=NOW)

    async def test_count_reached_for_session(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155591007")
        s = await _session(db_session, user)
        await crud.enqueue(
            db_session,
            rows=[
                _draft(user, key="c1", session_id=s.id),
                _draft(user, key="c2", session_id=s.id),
            ],
        )
        due = await crud.get_due(db_session, now=NOW)
        await crud.mark_sent(
            db_session, delivery=due[0], provider="twilio", provider_message_id="x", now=NOW
        )
        assert (
            await crud.count_reached_for_session(
                db_session, session_id=s.id, kind=NotificationKind.CIRCLE_ALERT
            )
            == 1
        )

    async def test_expire_overdue_returns_and_exhausts(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155591008")
        await crud.enqueue(
            db_session,
            rows=[
                _draft(
                    user,
                    key="exp",
                    next_attempt_at=NOW,
                    expires_at=NOW - timedelta(seconds=1),
                )
            ],
        )
        expired = await crud.expire_overdue(db_session, now=NOW)
        assert [e.dedupe_key for e in expired] == ["exp"]
        assert expired[0].status == DeliveryStatus.EXHAUSTED
