"""Account deletion orchestrator.

Owns the user-visible "delete my account" verb. Coordinates the soft-delete
marker, Stripe subscription cancellation, group-plan and sponsorship
side-effects, and the notification fan-out that the worker-tick reminders
then chase.

This module is intentionally the single entry point for deletion. Endpoints
call into here; the worker tick consults `deleted_at` directly but never
re-implements the soft-delete semantics.

Related:
- app/models/user.py (deleted_at column)
- app/services/stripe_service.py (cancel_subscription_at_period_end)
- app/crud/subscription.py (get_active_gifted_by_phone)
- docs/account-deletion-plan.md (state machine + policy decisions)
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import jwt
import stripe
from jwt import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.crud import crud_user
from app.crud.subscription import crud_subscription
from app.models.user import User
from app.services import stripe_service, subscription_service

# How long an /account/delete OTP-verified browser session stays
# authorized to fire the actual deletion. Short window: the user just
# clicks through the confirmation + types the gate, then submits.
# 10 minutes covers slow typing without exposing a long-lived token.
DELETION_TOKEN_TTL_MINUTES = 10
_DELETION_TOKEN_TYPE = "delete"

# Phone-scoped sign-in token TTL (sponsorship management at
# /sponsorships, redeemed via the short link /s/p/{token} ->
# GET /sponsorships/portal/{token}, whose button POSTs to redeem it). The link goes out via SMS, so users
# may take a few minutes to switch apps and tap. 10 minutes is enough
# without keeping a long-lived re-entry token around. The token itself is
# a one-time opaque DB row (app/models/sponsorship_sign_in_token.py,
# app/crud/sponsorship_sign_in_token.py) — not a JWT; this constant is the
# single source of truth for the TTL both mention in their docstrings.
SPONSORSHIP_TOKEN_TTL_MINUTES = 10


def mint_deletion_token(user_id: uuid.UUID) -> str:
    """Mint a short-lived JWT scoped to "delete this user."

    Used by the web flow: after OTP verification we hand the browser a
    cookie carrying this token. The final POST /account/delete/confirmations
    accepts the token, checks `type == "delete"`, and runs the
    orchestrator. No access tokens are issued — the user is NOT logging
    in to use the app, they're authorizing a single destructive action.
    """
    expire = datetime.now(UTC) + timedelta(minutes=DELETION_TOKEN_TTL_MINUTES)
    payload = {"exp": expire, "sub": str(user_id), "type": _DELETION_TOKEN_TYPE}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_deletion_token(token: str) -> uuid.UUID | None:
    """Validate a deletion token. Returns the user_id or None.

    Rejects expired tokens, wrong-type tokens (so an access_token can't
    be substituted), malformed JWTs, and invalid UUID payloads.
    """
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
    except PyJWTError:
        # benign: a bad or expired link token is an expected outcome (not-found page)
        return None
    if payload.get("type") != _DELETION_TOKEN_TYPE:
        return None
    sub = payload.get("sub")
    if not isinstance(sub, str):
        return None
    try:
        return uuid.UUID(sub)
    except ValueError:
        # benign: a malformed subject is treated as no user
        return None


# Prefix on User.stripe_customer_id after hard-purge. The column is
# NOT NULL + UNIQUE, so we can't blank it — we replace it with a
# sentinel that severs the link to the actual Stripe Customer (which
# stays in Stripe for tax/audit retention) while preserving uniqueness.
# Distinct from STRIPE_CUSTOMER_PENDING_PREFIX so the
# retry_pending_stripe_customers worker doesn't accidentally re-create
# a customer for a purged user.
STRIPE_CUSTOMER_PURGED_PREFIX = "purged:"

logger = logging.getLogger(__name__)

SponsorshipChoice = Literal["stop", "keep"]

# Grace window between soft-delete and hard-purge. Single source of truth
# for the user-visible deletion clock — re-imported by the API endpoints
# and the worker tick so the policy stays in one place.
DELETION_GRACE_DAYS = 30


class GraceExpiredError(Exception):
    """Raised when a user tries to restore after their grace window expired.

    The user's row may not be hard-purged yet (the worker runs hourly), but
    policy is that once we're past `deleted_at + DELETION_GRACE_DAYS` the
    only path back is re-signup with a fresh user_id. The endpoint maps
    this to HTTP 410 Gone.
    """


def scheduled_purge_at(deleted_at: datetime) -> datetime:
    """Compute the hard-purge eligibility date from a soft-delete marker.

    Centralized so the API responses and worker-tick query use the same
    arithmetic — changes to the grace window only need updating in one
    place.
    """
    return deleted_at + timedelta(days=DELETION_GRACE_DAYS)


async def soft_delete_user(db: AsyncSession, user: User) -> datetime:
    """Mark the user as soft-deleted.

    Stamps `deleted_at = now()` and clears `is_active`. Idempotent:
    calling on an already-soft-deleted user preserves the original
    timestamp so the 30-day grace clock can't be reset.

    Returns the canonical `deleted_at` timestamp — either the original
    (idempotent re-call) or the just-stamped value. Callers use this to
    build response payloads instead of re-reading `user.deleted_at`,
    which removes the need for runtime asserts that `-O` could strip.
    """
    if user.deleted_at is not None:
        return user.deleted_at
    timestamp = datetime.now(UTC)
    user.deleted_at = timestamp
    user.is_active = False
    # Revoke outstanding refresh tokens (defense-in-depth beyond is_active).
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    await db.refresh(user)
    return timestamp


async def restore_user(db: AsyncSession, user: User) -> None:
    """Reverse a soft-delete during the 30-day grace.

    Clears `deleted_at` and re-activates the account. Idempotent on
    already-active users.

    Primitive — endpoints should call `restore_user_account` so any
    grace-window bootstrap (e.g. resolving gifts that arrived while
    deleted) runs too.
    """
    if user.deleted_at is None:
        return
    user.deleted_at = None
    user.is_active = True
    await db.commit()
    await db.refresh(user)


async def restore_user_account(db: AsyncSession, user: User) -> None:
    """Restore a soft-deleted user and apply grace-window bootstrap.

    Why an orchestrator: gift subscriptions are keyed by phone number and
    can arrive at any time, including during the deletion grace window
    (the gifter has no way to know the recipient is mid-deletion). For
    an active user, `resolve_pending_gifts` runs as part of verify-otp;
    for a soft-deleted re-auth we skip that path so we don't mutate state
    on a sign-in that may not lead to a restore. On actual restore we
    have to catch up, otherwise gifts arriving during grace are silently
    stranded as PENDING and lost.

    `resolve_pending_gifts` is called unconditionally — even for users
    who were already active when restore was called. This keeps the
    flow idempotent on partial failure: if restore_user commits and
    resolve_pending_gifts then fails, the client retry still resolves
    the gifts (a gated-on-was_deleted variant would silently skip).
    The retry cost on already-resolved users is a single indexed query
    that finds no rows.

    Raises GraceExpiredError if the user is past their grace window
    (deleted_at < now - DELETION_GRACE_DAYS). The hard-purge worker
    runs hourly, so a past-grace row may not be anonymized yet — but
    policy is the user gets a fresh user_id via re-signup, not a
    restored stale row.
    """
    if user.deleted_at is not None and (
        user.deleted_at < datetime.now(UTC) - timedelta(days=DELETION_GRACE_DAYS)
    ):
        raise GraceExpiredError(
            "Grace window expired; re-sign-up creates a new account."
        )
    await restore_user(db, user)
    await subscription_service.resolve_pending_gifts(db, user.phone_number, user.id)


def _cancel_stripe_sub_best_effort(stripe_subscription_id: str) -> None:
    """Cancel a Stripe sub, logging failures instead of raising.

    Per docs/account-deletion-plan.md, a transient Stripe outage must NOT
    block the user's soft-delete — the hard-purge worker re-attempts at
    t=30d, and the user is unblocked from completing the deletion they
    requested. Logged failures are picked up by Bugsnag.
    """
    try:
        stripe_service.cancel_subscription_at_period_end(stripe_subscription_id)
    except stripe.StripeError as exc:
        logger.exception(
            "stripe_cancel_failed_during_deletion",
            extra={
                "stripe_subscription_id": stripe_subscription_id,
                "error": str(exc),
            },
        )


async def delete_user_account(
    db: AsyncSession,
    user: User,
    sponsorship_choices: dict[str, SponsorshipChoice] | None = None,
) -> datetime:
    """Initiate account deletion for `user`.

    Orchestration:
    1. Cancel the user's own active subscription at period end (if any).
       Group-plan owners' group subs are the user's own sub, so this
       branch handles the group-plan case automatically.
    2. For each subscription this user is currently sponsoring, apply the
       per-sub choice from `sponsorship_choices` (defaults to "stop").
       "keep" leaves the Stripe sub running so it can continue charging
       the user even after their account is gone — managed later via
       the phone-keyed sponsorship management page.
    3. Soft-delete the user. The hard-purge worker takes over at t=30d.

    Returns the canonical `deleted_at` timestamp; callers use this to
    compute scheduled_purge_at for response payloads.

    Idempotent: a re-call on an already-soft-deleted user returns the
    existing timestamp without re-applying any side effects.

    Stripe failures are logged, not raised — the user's deletion is the
    contract we owe them; the worker tick re-attempts the cancellations
    when it hard-purges later.
    """
    if user.deleted_at is not None:
        return user.deleted_at

    choices = sponsorship_choices or {}

    own_sub = await subscription_service.get_active_subscription(db, user.id)
    if own_sub is not None and own_sub.stripe_subscription_id:
        _cancel_stripe_sub_best_effort(own_sub.stripe_subscription_id)

    sponsored = await crud_subscription.get_active_gifted_by_phone(
        db, gifter_phone_id=user.phone_number_id
    )
    for sub in sponsored:
        if not sub.stripe_subscription_id:
            continue
        choice = choices.get(sub.stripe_subscription_id, "stop")
        if choice == "stop":
            _cancel_stripe_sub_best_effort(sub.stripe_subscription_id)

    return await soft_delete_user(db, user)


def _is_purged(user: User) -> bool:
    return user.stripe_customer_id.startswith(STRIPE_CUSTOMER_PURGED_PREFIX)


async def hard_purge_user(db: AsyncSession, user: User) -> None:
    """Anonymize a soft-deleted user in place.

    Scrubs every PII column on the user row but preserves user.id,
    user.phone_number_id, user.deleted_at, and user.is_active=False so
    that downstream FKs (alerts, sessions, referrals, admin logs) keep
    pointing at a row — they just now point at an anonymized stub.

    Severs the Stripe Customer link by overwriting stripe_customer_id
    with a `purged:<uuid>` sentinel. The actual Stripe Customer object
    remains in Stripe (for tax + audit retention and so the user's
    payment history is preserved on re-signup — see Phase 9). The link
    is re-established by phone metadata, not by this column.

    Idempotent: a re-purge on an already-purged user is a no-op so the
    worker tick can retry safely after partial failure.

    Caller is responsible for verifying the user is grace-expired (see
    crud_user.get_purge_eligible) — this function does NOT enforce
    "deleted_at < cutoff" so it can also be called by ops scripts.
    """
    if _is_purged(user):
        return

    # Race guard: between the worker's get_purge_eligible query and this
    # commit, the user could have called /me/restore from a parallel HTTP
    # connection (the advisory lock excludes other ticks, not user
    # requests). Refresh from the DB and bail if they're no longer soft-
    # deleted — otherwise we'd anonymize a user who just came back.
    await db.refresh(user)
    if user.deleted_at is None:
        logger.info(
            "hard_purge_skipped_user_restored",
            extra={"user_id": str(user.id)},
        )
        return

    user.full_name = None
    user.profile_photo_url = None
    user.expo_push_token = None
    user.share_code = None
    user.circle_invite_code = None
    user.stripe_customer_id = f"{STRIPE_CUSTOMER_PURGED_PREFIX}{uuid.uuid4()}"
    await db.commit()
    # Log BEFORE the refresh so a refresh failure after the commit doesn't
    # leave an audit gap. The commit is the durable boundary; everything
    # past it is recoverable from the DB state.
    logger.info("hard_purged_user", extra={"user_id": str(user.id)})
    await db.refresh(user)


async def process_pending_purges(db: AsyncSession) -> int:
    """Worker-tick entry point — anonymize every grace-expired user.

    Finds users whose grace window has passed AND who have no in-flight
    sessions, then hard-purges each. Returns the count processed (used
    by the tick's structured summary log).

    Per-user failures are caught and logged so one stuck user doesn't
    block the rest of the batch. The worker tick is the only caller
    in production; the `_safe` wrapper there also catches any escape.

    Cron-safety: the worker tick's Postgres advisory lock guarantees
    only one tick runs at a time across the whole system, so two
    concurrent purges of the same user are not possible.
    """
    cutoff = datetime.now(UTC) - timedelta(days=DELETION_GRACE_DAYS)
    eligible = await crud_user.get_purge_eligible(db, cutoff=cutoff)
    purged = 0
    for user in eligible:
        try:
            await hard_purge_user(db, user)
            purged += 1
        except Exception:
            logger.exception("hard_purge_user_failed", extra={"user_id": str(user.id)})
    return purged
