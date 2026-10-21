"""Accepting a circle-of-trust invite via the inviter's circle_invite_code.

Used by the web accept flow (POST /circles/{code}/accept) so a contact
WITHOUT the app can become an alertable member from the browser — explicit
acceptance is required before any alert SMS is sent to them
(docs/flow-review.md §4.2 B1/3.2, GroupMe intermediary-consent shape). The
mobile API's code-based accept endpoint had no in-app caller and was
removed 2026-09-22 (owner decision — Circle members use mobile web only).
Also backs the member's decline / leave actions
(POST /circles/{code}/decline|leave).

Related: web/routes_web.py, crud/circle_of_trust.py,
services/notification_helpers.py.
"""

import logging

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crud.circle_of_trust import crud_circle_of_trust
from app.models.circle_of_trust import CircleOfTrustMember, ContactStatus
from app.models.phone_number import PhoneNumber
from app.models.user import User

logger = logging.getLogger(__name__)


class SelfAcceptError(Exception):
    """The accepter is the inviter."""


class NoPendingInviteError(Exception):
    """No PENDING membership matches the accepter's phone for this inviter."""


async def get_member_for_accepter(
    db: AsyncSession, *, inviter: User, accepter: User
) -> CircleOfTrustMember | None:
    """The inviter's membership row whose contact phone is the accepter's."""
    result = await db.execute(
        select(CircleOfTrustMember)
        .join(
            PhoneNumber,
            CircleOfTrustMember.contact_phone_number_id == PhoneNumber.id,
        )
        .join(
            User,
            and_(
                User.phone_number_id == PhoneNumber.id,
                User.id == accepter.id,
            ),
        )
        .where(CircleOfTrustMember.user_id == inviter.id)
    )
    return result.scalars().first()


async def accept_circle_invite(
    db: AsyncSession, *, inviter: User, accepter: User
) -> CircleOfTrustMember:
    """Accept the inviter's pending invite for the accepter's phone.

    Activates the membership (PENDING → ACTIVE) and sends the welcome /
    consent-record SMS (best-effort). Raises SelfAcceptError or
    NoPendingInviteError for the caller to translate.
    """
    from app.services.notification_helpers import send_circle_welcome_sms

    if inviter.id == accepter.id:
        raise SelfAcceptError

    member = await get_member_for_accepter(db, inviter=inviter, accepter=accepter)
    if not member or member.status != ContactStatus.PENDING:
        raise NoPendingInviteError

    member = await crud_circle_of_trust.accept_invitation(db, contact=member)

    # The welcome SMS doubles as the consent record for future alert texts
    # (logged by the SMS provider). Never block acceptance on its failure.
    try:
        await send_circle_welcome_sms(accepter=accepter, inviter=inviter)
    except Exception:
        logger.exception("Failed to send circle welcome SMS")

    return member


async def decline_circle_invite(
    db: AsyncSession, *, inviter: User, decliner: User
) -> CircleOfTrustMember | None:
    """Decline the inviter's PENDING invite for the decliner's phone.

    Soft-removes the row (REMOVED) so a later re-invite revives it, same
    semantics as the removed v1 mobile endpoint and the deleted htmx
    dashboard handler (app/web/routes_htmx_profile.py, removed 2026-09-23).
    No-ops (returns None) when there's no matching PENDING row — e.g. an
    impostor's phone, or an invite that's already active/removed.
    """
    member = await get_member_for_accepter(db, inviter=inviter, accepter=decliner)
    if not member or member.status != ContactStatus.PENDING:
        return None
    return await crud_circle_of_trust.soft_set_status(
        db, contact=member, status=ContactStatus.REMOVED
    )


async def leave_circle(
    db: AsyncSession, *, inviter: User, member: User
) -> CircleOfTrustMember | None:
    """Leave the inviter's circle: soft-remove the member's ACTIVE row.

    SOFT (REMOVED), not the hard delete the old htmx handler did — keeps
    the row's identity so re-adding the same phone revives it instead of
    minting a new one. No-ops (returns None) when the member isn't
    currently ACTIVE in this circle.

    Notifies the inviter (owner) with the same cascade shape as the SMS
    STOP cascade (`sms_opt_out.cascade_circle_removal` ->
    `notification_helpers.fan_out_cascade_notifications`), tagged
    `reason="left"` so the "others remain" case uses leave-specific copy
    (CONTACT_LEFT) instead of the STOP wording (CONTACT_OPTED_OUT); the
    emptied-circle cases share their copy either way. Never blocks the
    leave itself — the membership is already removed and committed above
    by the time notification is attempted.
    """
    from app.services.notification_helpers import fan_out_cascade_notifications
    from app.services.sms_opt_out import compute_owner_impacts

    row = await get_member_for_accepter(db, inviter=inviter, accepter=member)
    if not row or row.status != ContactStatus.ACTIVE:
        return None
    removed = await crud_circle_of_trust.soft_set_status(
        db, contact=row, status=ContactStatus.REMOVED
    )

    try:
        name = removed.display_name or "A Circle member"
        impacts = await compute_owner_impacts(db, {inviter.id: (removed, name)})
        await fan_out_cascade_notifications(db, impacts, reason="left")
    except Exception:
        # A notification failure must never block the leave itself — the
        # membership removal above is already committed. Reported (not
        # swallowed): every except block reports or is benign, and a
        # dropped owner notification is not benign.
        logger.exception("Failed to notify owner of a web circle leave")
        # A DB error inside the fan-out (e.g. the outbox insert) aborts the
        # open transaction; roll it back so the request session stays usable
        # (get_db commits on exit). Only the un-committed notification work
        # is discarded — the leave was committed by soft_set_status above.
        await db.rollback()

    return removed
