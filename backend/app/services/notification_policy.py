"""Per-kind delivery policy + dedupe-key construction for the outbox.

Each NotificationKind has ONE policy describing which channels it dispatches on
(in parallel — never serial-gated), how many attempts + the backoff schedule,
when it expires, whether to poll Expo receipts (every push-carrying kind, so
delivery is auditable), and whether exhausting it escalates to the owner
("contact unreachable"). Keeping this as data means the reconciler has no
per-kind branching and adding a kind is a table entry, not a new code path.

Related: crud/notification_delivery.py, services/notification_outbox.py,
         models/notification_delivery.py.
"""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

from app.models.notification_delivery import DeliveryChannel, NotificationKind

_PUSH = DeliveryChannel.PUSH
_SMS = DeliveryChannel.SMS


@dataclass(frozen=True)
class DeliveryPolicy:
    channels: tuple[DeliveryChannel, ...]
    max_attempts: int
    # Per-attempt backoff; the last value repeats if attempts exceed its length.
    backoff_seconds: tuple[int, ...]
    # Fixed TTL from creation. None = the enqueuer sets a per-row expires_at
    # (owner reminders expire at deadline+grace).
    expires_after: timedelta | None
    # Poll Expo delivery receipts for this kind. True for every kind whose
    # channels include PUSH, so every push we send is auditable for delivery;
    # the SMS-only circle kinds (CIRCLE_ALERT, CIRCLE_RENUDGE, ALL_CLEAR,
    # ALERT_ACKNOWLEDGED) have no push to poll and stay False.
    track_expo_receipts: bool
    # On exhaustion, enqueue an owner "contact unreachable" notification.
    escalate_on_exhausted: bool


# Kinds directed AT the circle about the owner — the only ones allowed to
# escalate on exhaustion (guarded by the contract test).
CIRCLE_DIRECTED_KINDS = frozenset(
    {NotificationKind.CIRCLE_ALERT, NotificationKind.CIRCLE_RENUDGE}
)

_BROADCAST_BACKOFF = (60, 300, 900)

POLICIES: dict[NotificationKind, DeliveryPolicy] = {
    # SMS-only (owner decision): Circle members are notified by SMS only —
    # no push, regardless of whether they have the app. escalate_on_exhausted
    # now fires on a refused/exhausted SMS row.
    NotificationKind.CIRCLE_ALERT: DeliveryPolicy(
        channels=(_SMS,),
        max_attempts=6,
        backoff_seconds=(30, 60, 120, 300, 600, 900),
        expires_after=timedelta(hours=24),
        track_expo_receipts=False,
        escalate_on_exhausted=True,
    ),
    NotificationKind.CIRCLE_RENUDGE: DeliveryPolicy(
        channels=(_SMS,),
        max_attempts=3,
        backoff_seconds=(60, 300, 600),
        expires_after=timedelta(hours=2),
        track_expo_receipts=False,
        escalate_on_exhausted=False,
    ),
    NotificationKind.OWNER_REMINDER: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=(30, 60, 120),
        expires_after=None,  # per-row: deadline + grace
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # SMS only (2026-09-27 correction): send_owner_reminder has only ever
    # built an SMS DeliveryDraft directly (the at-deadline push is the
    # client's own local T-0 rung) — the PUSH channel here was declared but
    # never used. track_expo_receipts follows suit (no push to poll a
    # receipt for); see docs/notifications.md §3.
    NotificationKind.OWNER_DEADLINE: DeliveryPolicy(
        channels=(_SMS,),
        max_attempts=3,
        backoff_seconds=(30, 60, 120),
        expires_after=None,  # per-row: deadline + grace
        track_expo_receipts=False,
        escalate_on_exhausted=False,
    ),
    NotificationKind.SESSION_EXPIRED_OWNER: DeliveryPolicy(
        channels=(_PUSH, _SMS),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=1),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    NotificationKind.CIRCLE_ALERTED: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # SMS-only (owner decision): Circle members are notified by SMS only.
    NotificationKind.ALL_CLEAR: DeliveryPolicy(
        channels=(_SMS,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=False,
        escalate_on_exhausted=False,
    ),
    # SMS-only (owner decision 2026-07-18): acknowledgement news reaches
    # every circle member the same way regardless of whether they have the
    # app, and the owner gets it in Messages. No pushes.
    NotificationKind.ALERT_ACKNOWLEDGED: DeliveryPolicy(
        channels=(_SMS,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=False,
        escalate_on_exhausted=False,
    ),
    NotificationKind.CONTACT_UNREACHABLE: DeliveryPolicy(
        channels=(_PUSH, _SMS),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    NotificationKind.CONTACT_OPTED_OUT: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # Same policy shape as CONTACT_OPTED_OUT — a separate kind only so the
    # audit trail distinguishes a web leave from a STOP-cascade opt-out.
    NotificationKind.CONTACT_LEFT: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    NotificationKind.CIRCLE_EMPTIED: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    NotificationKind.CIRCLE_EMPTIED_MID_SESSION: DeliveryPolicy(
        channels=(_PUSH, _SMS),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    NotificationKind.DATA_DELETED: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # Owner/member-directed, not circle-directed — no escalation. Previously
    # a direct ExpoPushNotificationService.send_notification call with no
    # delivery row, no retry, no receipt (owner decision: every push auditable).
    NotificationKind.GROUP_PLAN_GRACE: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # Push + SMS backup so a denied-notifications dependent still hears their
    # coverage is ending. Previously two direct sends with no delivery row,
    # no retry, no receipt (owner decision: every push auditable).
    NotificationKind.SUBSCRIPTION_LAPSE: DeliveryPolicy(
        channels=(_PUSH, _SMS),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # Account-holder directed, not circle-directed — no escalation. SMS
    # would be blocked at the opt-out gate anyway (their own phone just
    # opted out), so push-only. Previously a direct
    # ExpoPushNotificationService.send_notification call with no delivery
    # row, no retry, no receipt (owner decision: every push auditable).
    NotificationKind.ACCOUNT_HOLDER_UNSUBSCRIBED: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
    # Same shape as ACCOUNT_HOLDER_UNSUBSCRIBED — sent grace_days later,
    # only when a subscription was actually set to cancel. Previously a
    # direct send_notification call with no delivery row, no retry, no
    # receipt (owner decision: every push auditable).
    NotificationKind.ACCOUNT_HOLDER_SUBSCRIPTION_CANCELLED: DeliveryPolicy(
        channels=(_PUSH,),
        max_attempts=3,
        backoff_seconds=_BROADCAST_BACKOFF,
        expires_after=timedelta(hours=6),
        track_expo_receipts=True,
        escalate_on_exhausted=False,
    ),
}


def policy_for(kind: NotificationKind) -> DeliveryPolicy:
    return POLICIES[kind]


def make_dedupe_key(
    kind: NotificationKind,
    *,
    scope_id: UUID | str,
    channel: DeliveryChannel,
    recipient_user_id: UUID | None = None,
    recipient_phone_id: UUID | None = None,
    occurrence: str | None = None,
) -> str:
    """Deterministic identity for a delivery so enqueue is idempotent.

    `{kind}:{scope_id}:{recipient}:{channel}[:{occurrence}]` — scope_id is the
    session id (session kinds) or owner user id (cascade kinds); occurrence
    disambiguates legitimate repeats (e.g. an owner reminder's deadline+minutes,
    a re-nudge round, or — for the four circle-cascade kinds — the removed
    membership's `{membership_id}:{status_changed_at_iso}`, see
    notification_helpers._cascade_occurrence). An occurrence may itself contain
    ':' (an ISO timestamp does), so never split a key to parse it.
    """
    recipient = (
        f"u:{recipient_user_id}"
        if recipient_user_id is not None
        else f"p:{recipient_phone_id}"
    )
    parts = [kind.value, str(scope_id), recipient, channel.value]
    if occurrence:
        parts.append(occurrence)
    return ":".join(parts)
