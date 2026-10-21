"""The outbox dispatch claim: crud_notification_delivery.claim / get_due and
send_due_deliveries' use of them to make sure exactly one dispatcher sends a
given row even though send_due_deliveries is invoked from more than one place
(the worker tick vs. an inline request-path dispatch via
enqueue_and_send/process_overdue, which runs outside the tick's advisory
lock).

Note on concurrency: `db_session` (conftest.py) gives each test a single
connection with a savepoint per test — a second, truly independent connection
to the test database would not see this connection's uncommitted rows at all
(Postgres has no dirty reads), so a genuine two-connection race can't be
driven inside one test here (the same constraint that makes
test_worker_tick_lock.py mock the lock rather than race two real workers).
Instead these tests drive the two dispatchers sequentially, with the claim
persisted (committed) between them — which is exactly the state a second,
real, concurrent dispatcher would observe.

Related: app/crud/notification_delivery.py, app/services/notification_outbox.py.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.notification_delivery import CLAIM_TTL, DeliveryDraft
from app.crud.notification_delivery import crud_notification_delivery as crud
from app.models.notification_delivery import (
    DeliveryChannel,
    DeliveryStatus,
    NotificationDelivery,
    NotificationKind,
)
from app.services import notification_outbox as outbox
from app.services.sms import SMSProvider, SMSResult
from tests.helpers import create_test_user

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=UTC)


def _draft(user, *, key, next_attempt_at=NOW) -> DeliveryDraft:
    return DeliveryDraft(
        dedupe_key=key,
        kind=NotificationKind.CIRCLE_ALERT,
        channel=DeliveryChannel.SMS,
        body="hi",
        next_attempt_at=next_attempt_at,
        recipient_phone_id=user.phone_number_id,
    )


async def _persisted_claim(db: AsyncSession, delivery_id):
    """The claimed_at value in the database (not the in-memory attribute)."""
    return (
        await db.execute(
            select(NotificationDelivery.claimed_at).where(
                NotificationDelivery.id == delivery_id
            )
        )
    ).scalar_one()


def _patch_sms(monkeypatch, calls: list[str]):
    async def fake(db, phone, body, **k):
        calls.append(phone)
        return SMSResult(success=True, message_id="sid", provider=SMSProvider.TWILIO)

    monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)


@pytest.mark.asyncio
class TestClaimAtomicity:
    async def test_claim_wins_only_once(self, db_session: AsyncSession):
        """The core compare-and-swap: a second claim attempt for the same
        (unclaimed-since) row loses, exactly as a second concurrent dispatcher
        would."""
        user = await create_test_user(db_session, phone_number="+14155593001")
        await crud.enqueue(db_session, rows=[_draft(user, key="c1")])
        [d] = await crud.get_due(db_session, now=NOW)

        first = await crud.claim(db_session, delivery_id=d.id, now=NOW)
        await db_session.commit()
        second = await crud.claim(db_session, delivery_id=d.id, now=NOW)
        await db_session.commit()

        assert first is True
        assert second is False


@pytest.mark.asyncio
class TestSendDueDeliveriesRespectsClaim:
    async def test_row_claimed_by_another_dispatcher_is_sent_exactly_once(
        self, db_session: AsyncSession, monkeypatch
    ):
        """Two dispatch calls sharing the same due row: once dispatcher A's
        claim is persisted, dispatcher B's send_due_deliveries must not also
        send it."""
        user = await create_test_user(db_session, phone_number="+14155593002")
        await crud.enqueue(db_session, rows=[_draft(user, key="c2")])
        [d] = await crud.get_due(db_session, now=NOW)
        calls: list[str] = []
        _patch_sms(monkeypatch, calls)

        # Dispatcher A claims the row and is still mid-flight (hasn't sent yet).
        won = await crud.claim(db_session, delivery_id=d.id, now=NOW)
        await db_session.commit()
        assert won is True

        # Dispatcher B's tick starts right after — the row is claimed and
        # fresh, so B's due-scan must not see it at all.
        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert calls == []
        assert counts["sent"] == 0
        assert counts["claim_lost"] == 0  # never reached: get_due excluded it

        # A now finishes the send (what actually happens inside
        # send_due_deliveries once it owns the claim).
        await crud.mark_sent(
            db_session, delivery=d, provider="twilio", provider_message_id="m1", now=NOW
        )
        await db_session.commit()
        assert d.status == DeliveryStatus.SENT
        # Sent exactly once — B never dispatched it.
        assert len(calls) == 0

    async def test_stale_claim_is_re_dispatched(
        self, db_session: AsyncSession, monkeypatch
    ):
        """A claim older than CLAIM_TTL (a crashed dispatcher) must not block
        the row forever."""
        user = await create_test_user(db_session, phone_number="+14155593003")
        await crud.enqueue(db_session, rows=[_draft(user, key="c3")])
        [d] = await crud.get_due(db_session, now=NOW)

        stale_claim_time = NOW - CLAIM_TTL - timedelta(seconds=1)
        won = await crud.claim(
            db_session, delivery_id=d.id, now=NOW, claim_time=stale_claim_time
        )
        await db_session.commit()
        assert won is True

        calls: list[str] = []
        _patch_sms(monkeypatch, calls)
        counts = await outbox.send_due_deliveries(db_session, now=NOW)

        assert counts["sent"] == 1
        assert len(calls) == 1
        await db_session.refresh(d)
        assert d.status == DeliveryStatus.SENT

    async def test_second_claim_attempt_within_ttl_is_refused(
        self, db_session: AsyncSession
    ):
        """A claim well inside CLAIM_TTL still refuses a second claimant
        (the mirror of the stale-claim case above)."""
        user = await create_test_user(db_session, phone_number="+14155593004")
        await crud.enqueue(db_session, rows=[_draft(user, key="c4")])
        [d] = await crud.get_due(db_session, now=NOW)

        won = await crud.claim(db_session, delivery_id=d.id, now=NOW)
        await db_session.commit()
        assert won is True

        still_fresh = NOW + (CLAIM_TTL - timedelta(seconds=1))
        second = await crud.claim(db_session, delivery_id=d.id, now=still_fresh)
        await db_session.commit()
        assert second is False


@pytest.mark.asyncio
class TestClaimVisibility:
    async def test_claimed_but_unfinished_row_is_not_visible_to_get_due(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155593005")
        await crud.enqueue(db_session, rows=[_draft(user, key="c5")])
        [d] = await crud.get_due(db_session, now=NOW)

        won = await crud.claim(db_session, delivery_id=d.id, now=NOW)
        await db_session.commit()
        assert won is True

        # Still PENDING (never dispatched) but freshly claimed — must be
        # excluded from the due scan.
        assert await crud.get_due(db_session, now=NOW) == []

    async def test_stale_claimed_row_is_visible_to_get_due(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155593006")
        await crud.enqueue(db_session, rows=[_draft(user, key="c6")])
        [d] = await crud.get_due(db_session, now=NOW)

        stale_claim_time = NOW - CLAIM_TTL - timedelta(seconds=1)
        assert (
            await crud.claim(
                db_session, delivery_id=d.id, now=NOW, claim_time=stale_claim_time
            )
            is True
        )
        await db_session.commit()

        keys = {row.dedupe_key for row in await crud.get_due(db_session, now=NOW)}
        assert keys == {"c6"}


@pytest.mark.asyncio
class TestClaimClearedOnTransition:
    async def test_mark_sent_clears_claim(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155593007")
        await crud.enqueue(db_session, rows=[_draft(user, key="c7")])
        [d] = await crud.get_due(db_session, now=NOW)
        assert await crud.claim(db_session, delivery_id=d.id, now=NOW) is True
        await db_session.refresh(d)  # as send_due_deliveries does after a win
        assert d.claimed_at is not None
        await crud.mark_sent(
            db_session, delivery=d, provider="twilio", provider_message_id="m7", now=NOW
        )
        assert await _persisted_claim(db_session, d.id) is None

    async def test_mark_failed_with_backoff_clears_claim_and_row_becomes_due_again(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155593008")
        await crud.enqueue(db_session, rows=[_draft(user, key="c8")])
        [d] = await crud.get_due(db_session, now=NOW)
        assert await crud.claim(db_session, delivery_id=d.id, now=NOW) is True
        await db_session.refresh(d)  # as send_due_deliveries does after a win
        assert d.claimed_at is not None
        await crud.mark_failed_with_backoff(
            db_session,
            delivery=d,
            backoff_seconds=(30,),
            max_attempts=5,
            error="boom",
            now=NOW,
        )
        assert await _persisted_claim(db_session, d.id) is None
        assert d.status == DeliveryStatus.FAILED

        # Backoff is much shorter than CLAIM_TTL — without clearing the claim
        # the row would wrongly stay hidden from get_due until CLAIM_TTL
        # elapses, well after its own backoff has.
        later = NOW + timedelta(seconds=31)
        keys = {row.dedupe_key for row in await crud.get_due(db_session, now=later)}
        assert keys == {"c8"}

    async def test_mark_terminal_clears_claim(self, db_session: AsyncSession):
        user = await create_test_user(db_session, phone_number="+14155593009")
        await crud.enqueue(db_session, rows=[_draft(user, key="c9")])
        [d] = await crud.get_due(db_session, now=NOW)
        assert await crud.claim(db_session, delivery_id=d.id, now=NOW) is True
        await db_session.refresh(d)  # as send_due_deliveries does after a win
        assert d.claimed_at is not None
        await crud.mark_terminal(
            db_session,
            delivery=d,
            status=DeliveryStatus.REFUSED,
            error="no phone",
            now=NOW,
        )
        assert await _persisted_claim(db_session, d.id) is None


@pytest.mark.asyncio
class TestEnqueueAndSendThenTick:
    async def test_enqueue_and_send_then_immediate_tick_sends_once(
        self, db_session: AsyncSession, monkeypatch
    ):
        """enqueue_and_send dispatches inline (the request-path caller); a
        worker tick landing right after must not re-send the same row."""
        user = await create_test_user(db_session, phone_number="+14155593010")
        calls: list[str] = []
        _patch_sms(monkeypatch, calls)

        await outbox.enqueue_and_send(
            db_session, rows=[_draft(user, key="c10")], now=NOW
        )
        assert len(calls) == 1

        # The tick, immediately after.
        counts = await outbox.send_due_deliveries(db_session, now=NOW)
        assert counts["sent"] == 0
        assert len(calls) == 1  # still exactly one send


def _race_get_due(monkeypatch, **finished_values):
    """Make the dispatcher's get_due hand back rows that another dispatcher
    then finishes before this one claims them: between the select and the
    claim, the rows are rewritten in the database (not in the identity map —
    exactly the stale in-memory copy the real race leaves behind with
    expire_on_commit=False)."""
    real_get_due = crud.get_due

    async def racing_get_due(db, *, now, limit=100):
        rows = await real_get_due(db, now=now, limit=limit)
        if rows:
            await db.execute(
                update(NotificationDelivery)
                .where(NotificationDelivery.id.in_([r.id for r in rows]))
                .values(**finished_values)
                .execution_options(synchronize_session=False)
            )
        return rows

    monkeypatch.setattr(outbox.crud_nd, "get_due", racing_get_due)


@pytest.mark.asyncio
class TestStaleCopyCannotReclaim:
    """Every transition clears claimed_at, so the claim must ALSO re-assert
    that the row is still due — otherwise a dispatcher holding a stale copy of
    a row someone else already sent would win an 'unclaimed' row and send it
    again."""

    async def test_row_sent_by_another_dispatcher_is_not_sent_again(
        self, db_session: AsyncSession, monkeypatch
    ):
        user = await create_test_user(db_session, phone_number="+14155593001")
        await crud.enqueue(db_session, rows=[_draft(user, key="r1")])
        await db_session.commit()
        calls: list[str] = []
        _patch_sms(monkeypatch, calls)
        _race_get_due(monkeypatch, status=DeliveryStatus.SENT, claimed_at=None)

        counts = await outbox.send_due_deliveries(db_session, now=NOW)

        assert calls == []
        assert counts["claim_lost"] == 1
        assert counts["sent"] == 0

    async def test_row_in_backoff_after_another_dispatchers_attempt_is_not_retried(
        self, db_session: AsyncSession, monkeypatch
    ):
        user = await create_test_user(db_session, phone_number="+14155593002")
        await crud.enqueue(db_session, rows=[_draft(user, key="r2")])
        await db_session.commit()
        calls: list[str] = []
        _patch_sms(monkeypatch, calls)
        _race_get_due(
            monkeypatch,
            status=DeliveryStatus.FAILED,
            attempt_count=1,
            next_attempt_at=NOW + timedelta(seconds=30),
            claimed_at=None,
        )

        counts = await outbox.send_due_deliveries(db_session, now=NOW)

        assert calls == []
        assert counts["claim_lost"] == 1


@pytest.mark.asyncio
class TestConcurrentDispatchSendsOnce:
    async def test_second_dispatcher_running_mid_send_sends_nothing(
        self, db_session: AsyncSession, monkeypatch
    ):
        """Dispatcher B runs while A is inside the provider call for the row
        (A's claim is committed): the provider is called exactly once."""
        user = await create_test_user(db_session, phone_number="+14155593003")
        await crud.enqueue(db_session, rows=[_draft(user, key="r3")])
        await db_session.commit()
        calls: list[str] = []
        nested: list[dict[str, int]] = []

        async def fake(db, phone, body, **k):
            calls.append(phone)
            if len(calls) == 1:
                nested.append(await outbox.send_due_deliveries(db, now=NOW))
            return SMSResult(
                success=True, message_id="sid", provider=SMSProvider.TWILIO
            )

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)

        counts = await outbox.send_due_deliveries(db_session, now=NOW)

        assert len(calls) == 1
        assert counts["sent"] == 1
        assert nested[0]["sent"] == 0

    async def test_claim_is_stamped_with_the_wall_clock_not_the_batch_now(
        self, db_session: AsyncSession, monkeypatch
    ):
        """A tick's `now` is taken at tick start; a batch that runs long must
        not stamp a claim that is already stale (and so stealable by a
        dispatcher using the current time) while its send is in flight."""
        tick_started = datetime.now(UTC) - timedelta(hours=1)
        user = await create_test_user(db_session, phone_number="+14155593004")
        await crud.enqueue(
            db_session, rows=[_draft(user, key="r4", next_attempt_at=tick_started)]
        )
        await db_session.commit()
        visible_mid_send: list[list] = []

        async def fake(db, phone, body, **k):
            visible_mid_send.append(await crud.get_due(db, now=datetime.now(UTC)))
            return SMSResult(
                success=True, message_id="sid", provider=SMSProvider.TWILIO
            )

        monkeypatch.setattr(outbox.sms_opt_out, "gated_send_sms", fake)

        await outbox.send_due_deliveries(db_session, now=tick_started)

        assert visible_mid_send == [[]]


@pytest.mark.asyncio
class TestExpiryRespectsClaim:
    async def test_expiry_skips_a_fresh_claim_and_reaps_a_stale_one(
        self, db_session: AsyncSession
    ):
        """A row mid-dispatch must not be flipped to EXHAUSTED underneath its
        dispatcher (a false 'contact unreachable'); an abandoned claim is
        reaped once it ages out."""
        user = await create_test_user(db_session, phone_number="+14155593005")
        draft = _draft(user, key="r5")
        draft.expires_at = NOW + timedelta(seconds=10)
        await crud.enqueue(db_session, rows=[draft])
        [d] = await crud.get_due(db_session, now=NOW)
        assert await crud.claim(db_session, delivery_id=d.id, now=NOW) is True
        await db_session.commit()

        assert (
            await crud.expire_overdue(db_session, now=NOW + timedelta(minutes=1)) == []
        )

        reaped = await crud.expire_overdue(
            db_session, now=NOW + CLAIM_TTL + timedelta(minutes=1)
        )
        assert [r.id for r in reaped] == [d.id]
        assert reaped[0].status == DeliveryStatus.EXHAUSTED
        assert await _persisted_claim(db_session, d.id) is None
