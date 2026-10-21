"""Tests for the account deletion orchestrator.

Related files:
- app/services/account_deletion.py
- docs/account-deletion-plan.md
"""
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.phone_number import crud_phone_number
from app.models.subscription import (
    Subscription,
    SubscriptionSource,
    SubscriptionStatus,
)
from app.models.user import User
from app.services import account_deletion, subscription_service
from app.services.account_deletion import DELETION_GRACE_DAYS
from tests.helpers import create_test_subscription, create_test_user


@pytest.mark.asyncio
class TestSoftDeleteUser:
    async def test_stamps_deleted_at_and_deactivates(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559001")
        assert user.deleted_at is None
        assert user.is_active is True

        await account_deletion.soft_delete_user(db_session, user)

        assert user.deleted_at is not None
        assert user.is_active is False

    async def test_idempotent_preserves_original_timestamp(
        self, db_session: AsyncSession
    ):
        """Calling twice must NOT reset the grace clock — otherwise a
        retry could quietly extend the user's purge date forever."""
        user = await create_test_user(db_session, phone_number="+14155559002")
        original = datetime.now(UTC) - timedelta(days=5)
        user.deleted_at = original
        user.is_active = False
        await db_session.commit()

        await account_deletion.soft_delete_user(db_session, user)

        assert user.deleted_at is not None
        assert abs((user.deleted_at - original).total_seconds()) < 1


@pytest.mark.asyncio
class TestRestoreUser:
    async def test_clears_deleted_at_and_reactivates(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559003")
        await account_deletion.soft_delete_user(db_session, user)
        assert user.deleted_at is not None

        await account_deletion.restore_user(db_session, user)

        assert user.deleted_at is None
        assert user.is_active is True

    async def test_idempotent_on_active_user(
        self, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559004")
        await account_deletion.restore_user(db_session, user)
        assert user.deleted_at is None
        assert user.is_active is True


@pytest.mark.asyncio
class TestRestoreUserAccount:
    async def test_resolves_gifts_arriving_during_grace(
        self, db_session: AsyncSession
    ):
        """A sponsor can gift a sub during the recipient's grace window
        — they don't know the recipient is mid-deletion. On restore,
        those PENDING gifts must attach to the user, else they're lost."""
        phone = "+14155559200"
        user = await create_test_user(db_session, phone_number=phone)

        # Soft-delete the user.
        await account_deletion.soft_delete_user(db_session, user)

        # A gift arrives during grace — Stripe webhook creates a PENDING
        # sub keyed by phone, user_id=None.
        await subscription_service.create_subscription(
            db_session,
            phone_number=phone,
            plan_type="monthly",
            source=SubscriptionSource.STRIPE_GIFT.value,
            user_id=None,
            auto_renew=False,
        )

        await account_deletion.restore_user_account(db_session, user)

        assert user.deleted_at is None
        assert user.is_active is True
        # The gift is now attached to the user as ACTIVE.
        sub = await subscription_service.get_active_subscription(
            db_session, user.id
        )
        assert sub is not None
        assert sub.source == SubscriptionSource.STRIPE_GIFT

    async def test_raises_grace_expired_for_past_grace_user(
        self, db_session: AsyncSession
    ):
        """Past 30 days the row may not be hard-purged yet (worker is
        hourly), but policy is fresh user_id on re-signup. Reject
        restore so we don't clobber a row destined for anonymization."""
        user = await create_test_user(db_session, phone_number="+14155559210")
        user.deleted_at = datetime.now(UTC) - timedelta(
            days=DELETION_GRACE_DAYS + 1
        )
        user.is_active = False
        await db_session.commit()

        with pytest.raises(account_deletion.GraceExpiredError):
            await account_deletion.restore_user_account(db_session, user)

        await db_session.refresh(user)
        # Row left untouched — no half-restore.
        assert user.deleted_at is not None
        assert user.is_active is False

    async def test_resolve_runs_even_on_already_active_user(
        self, db_session: AsyncSession
    ):
        """resolve_pending_gifts is called unconditionally so that a
        client retry after a partial failure (restore committed, resolve
        crashed) still catches up the gifts. The cost on a clean active
        user is one indexed query returning zero rows.

        This is the explicit trade-off documented in
        restore_user_account: idempotency under partial failure beats
        skipping a no-op query."""
        phone = "+14155559201"
        user = await create_test_user(db_session, phone_number=phone)

        with patch(
            "app.services.account_deletion.subscription_service.resolve_pending_gifts"
        ) as mock_resolve:
            await account_deletion.restore_user_account(db_session, user)

        mock_resolve.assert_called_once_with(db_session, phone, user.id)


async def _sponsor_a_sub(
    db: AsyncSession, *, sponsor: User, beneficiary_phone: str, stripe_sub_id: str
) -> Subscription:
    """Create an active subscription with `sponsor` as the gifter."""
    bene_phone, _ = await crud_phone_number.get_or_create(db, number=beneficiary_phone)
    now = datetime.now(UTC)
    sub = Subscription(
        phone_number_id=bene_phone.id,
        plan_type="monthly",
        status=SubscriptionStatus.ACTIVE.value,
        source=SubscriptionSource.STRIPE_GIFT.value,
        gifted_by_phone_id=sponsor.phone_number_id,
        stripe_subscription_id=stripe_sub_id,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)
    return sub


@pytest.mark.asyncio
class TestDeleteUserAccount:
    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_soft_deletes_and_cancels_own_subscription(
        self, mock_cancel, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559100")
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_own_111"
        await db_session.commit()

        await account_deletion.delete_user_account(db_session, user)

        assert user.deleted_at is not None
        assert user.is_active is False
        mock_cancel.assert_called_once_with("sub_own_111")

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_no_subscription_still_soft_deletes(
        self, mock_cancel, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559101")

        await account_deletion.delete_user_account(db_session, user)

        assert user.deleted_at is not None
        mock_cancel.assert_not_called()

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_already_deleted_is_noop(
        self, mock_cancel, db_session: AsyncSession
    ):
        """A re-call must not re-cancel Stripe subs or extend the grace clock."""
        user = await create_test_user(db_session, phone_number="+14155559102")
        original_marker = datetime.now(UTC) - timedelta(days=5)
        user.deleted_at = original_marker
        await db_session.commit()

        await account_deletion.delete_user_account(db_session, user)

        assert abs((user.deleted_at - original_marker).total_seconds()) < 1
        mock_cancel.assert_not_called()

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_sponsored_subs_default_to_stop(
        self, mock_cancel, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559103")
        await _sponsor_a_sub(
            db_session,
            sponsor=user,
            beneficiary_phone="+14155559104",
            stripe_sub_id="sub_gift_aaa",
        )
        await _sponsor_a_sub(
            db_session,
            sponsor=user,
            beneficiary_phone="+14155559105",
            stripe_sub_id="sub_gift_bbb",
        )

        await account_deletion.delete_user_account(db_session, user)

        called_ids = {c.args[0] for c in mock_cancel.call_args_list}
        assert called_ids == {"sub_gift_aaa", "sub_gift_bbb"}

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_sponsored_sub_kept_when_flagged_keep(
        self, mock_cancel, db_session: AsyncSession
    ):
        user = await create_test_user(db_session, phone_number="+14155559110")
        await _sponsor_a_sub(
            db_session,
            sponsor=user,
            beneficiary_phone="+14155559111",
            stripe_sub_id="sub_keep_xxx",
        )
        await _sponsor_a_sub(
            db_session,
            sponsor=user,
            beneficiary_phone="+14155559112",
            stripe_sub_id="sub_stop_yyy",
        )

        await account_deletion.delete_user_account(
            db_session,
            user,
            sponsorship_choices={"sub_keep_xxx": "keep", "sub_stop_yyy": "stop"},
        )

        called_ids = {c.args[0] for c in mock_cancel.call_args_list}
        assert called_ids == {"sub_stop_yyy"}

    @patch(
        "app.services.account_deletion.stripe_service.cancel_subscription_at_period_end"
    )
    async def test_stripe_failure_does_not_block_soft_delete(
        self, mock_cancel, db_session: AsyncSession
    ):
        """The user's deletion is the contract — Stripe transient errors
        must not strand them in 'partially deleted' state."""
        mock_cancel.side_effect = stripe.StripeError("Stripe API down")
        user = await create_test_user(db_session, phone_number="+14155559120")
        sub = await create_test_subscription(db_session, user)
        sub.stripe_subscription_id = "sub_will_fail"
        await db_session.commit()

        await account_deletion.delete_user_account(db_session, user)

        assert user.deleted_at is not None
        assert user.is_active is False


@pytest.mark.asyncio
class TestHardPurgeUser:
    async def test_scrubs_pii_columns(self, db_session: AsyncSession):
        user = await create_test_user(
            db_session,
            phone_number="+14155559300",
            full_name="Alex Real",
            expo_push_token="ExponentPushToken[xxx]",
            share_code="ABCD1234",
            circle_invite_code="WXYZ5678",
            profile_photo_url="https://blob/photo.jpg",
        )
        user.deleted_at = datetime.now(UTC) - timedelta(days=DELETION_GRACE_DAYS + 1)
        await db_session.commit()
        original_id = user.id
        original_phone_id = user.phone_number_id
        original_stripe = user.stripe_customer_id

        await account_deletion.hard_purge_user(db_session, user)

        await db_session.refresh(user)
        assert user.full_name is None
        assert user.profile_photo_url is None
        assert user.expo_push_token is None
        assert user.share_code is None
        assert user.circle_invite_code is None
        # Stripe link severed but column still satisfies NOT NULL + UNIQUE.
        assert user.stripe_customer_id.startswith(
            account_deletion.STRIPE_CUSTOMER_PURGED_PREFIX
        )
        assert user.stripe_customer_id != original_stripe
        # FK-bearing columns preserved so downstream rows still resolve.
        assert user.id == original_id
        assert user.phone_number_id == original_phone_id

    async def test_idempotent_on_already_purged_user(
        self, db_session: AsyncSession
    ):
        """Worker tick can re-attempt purge on transient failure without
        rewriting the stripe sentinel (which would silently break audit
        trails that record 'when did this customer link get severed')."""
        user = await create_test_user(db_session, phone_number="+14155559301")
        user.deleted_at = datetime.now(UTC) - timedelta(days=DELETION_GRACE_DAYS + 1)
        await db_session.commit()
        await account_deletion.hard_purge_user(db_session, user)
        first_sentinel = user.stripe_customer_id

        await account_deletion.hard_purge_user(db_session, user)

        await db_session.refresh(user)
        assert user.stripe_customer_id == first_sentinel

    async def test_skips_if_user_restored_between_query_and_purge(
        self, db_session: AsyncSession
    ):
        """Race guard: between get_purge_eligible and the loop's call
        here, a concurrent HTTP /me/restore can clear deleted_at. The
        purge must read the current row from the DB and bail rather
        than anonymize a user who just came back."""
        user = await create_test_user(
            db_session,
            phone_number="+14155559310",
            full_name="Came Back",
        )
        user.deleted_at = datetime.now(UTC) - timedelta(
            days=DELETION_GRACE_DAYS + 1
        )
        await db_session.commit()

        # Worker has the user in memory with deleted_at set...
        in_memory = user

        # ...but a concurrent restore cleared it (simulate via direct
        # row update, which is what the parallel HTTP transaction would
        # do).
        user.deleted_at = None
        user.is_active = True
        await db_session.commit()

        await account_deletion.hard_purge_user(db_session, in_memory)

        await db_session.refresh(in_memory)
        assert in_memory.full_name == "Came Back"  # NOT scrubbed
        assert in_memory.deleted_at is None
        assert in_memory.is_active is True

    async def test_preserves_deleted_at_and_is_active(
        self, db_session: AsyncSession
    ):
        """The audit trail of 'when was this user soft-deleted' must
        survive hard purge. And is_active stays False so any stale
        token can't authenticate the anonymized stub."""
        user = await create_test_user(db_session, phone_number="+14155559302")
        deleted_at = datetime.now(UTC) - timedelta(days=DELETION_GRACE_DAYS + 1)
        user.deleted_at = deleted_at
        user.is_active = False
        await db_session.commit()

        await account_deletion.hard_purge_user(db_session, user)

        await db_session.refresh(user)
        assert user.deleted_at is not None
        assert abs((user.deleted_at - deleted_at).total_seconds()) < 1
        assert user.is_active is False


@pytest.mark.asyncio
class TestProcessPendingPurges:
    async def test_purges_grace_expired_users(
        self, db_session: AsyncSession
    ):
        now = datetime.now(UTC)
        past_grace = await create_test_user(
            db_session, phone_number="+14155559400", full_name="Past Grace"
        )
        past_grace.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 1)
        in_grace = await create_test_user(
            db_session, phone_number="+14155559401", full_name="Still In Grace"
        )
        in_grace.deleted_at = now - timedelta(days=1)
        await db_session.commit()

        count = await account_deletion.process_pending_purges(db_session)

        assert count == 1
        await db_session.refresh(past_grace)
        await db_session.refresh(in_grace)
        assert past_grace.full_name is None  # purged
        assert in_grace.full_name == "Still In Grace"  # still in grace

    async def test_per_user_failure_does_not_block_batch(
        self, db_session: AsyncSession
    ):
        """If one user's purge raises, the rest of the batch must still
        complete. Worker tick will catch the per-tick exception via
        its own _safe wrapper either way; this is the inner-loop
        guarantee."""
        now = datetime.now(UTC)
        users = []
        for i in range(3):
            u = await create_test_user(
                db_session, phone_number=f"+1415555941{i}", full_name=f"User{i}"
            )
            u.deleted_at = now - timedelta(days=DELETION_GRACE_DAYS + 1)
            users.append(u)
        await db_session.commit()

        real_purge = account_deletion.hard_purge_user
        call_count = {"n": 0}

        async def flaky(db, user):
            call_count["n"] += 1
            if call_count["n"] == 2:  # second call blows up
                raise RuntimeError("transient")
            await real_purge(db, user)

        with patch(
            "app.services.account_deletion.hard_purge_user", side_effect=flaky
        ):
            count = await account_deletion.process_pending_purges(db_session)

        # 3 attempts, 1 failed → 2 purged.
        assert count == 2
        purged = 0
        for u in users:
            await db_session.refresh(u)
            if u.full_name is None:
                purged += 1
        assert purged == 2

    async def test_empty_when_no_eligible_users(
        self, db_session: AsyncSession
    ):
        count = await account_deletion.process_pending_purges(db_session)
        assert count == 0
