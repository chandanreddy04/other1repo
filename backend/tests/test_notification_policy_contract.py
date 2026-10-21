"""Delivery-policy invariants + dedupe-key construction.

Every NotificationKind must have a policy; escalation is reserved for
circle-directed kinds; receipt polling implies a push channel. (The kind ->
mobile data.type mapping is asserted in B.4, where the enqueue sites build the
push payloads.)

Related: app/services/notification_policy.py.
"""

from uuid import uuid4

from app.models.notification_delivery import DeliveryChannel, NotificationKind
from app.services.notification_policy import (
    CIRCLE_DIRECTED_KINDS,
    POLICIES,
    make_dedupe_key,
    policy_for,
)


class TestPolicyContract:
    def test_every_kind_has_a_policy(self):
        for kind in NotificationKind:
            assert kind in POLICIES, f"no policy for {kind}"

    def test_policies_are_well_formed(self):
        for kind, policy in POLICIES.items():
            assert policy.channels, f"{kind} has no channels"
            assert policy.max_attempts >= 1, f"{kind} max_attempts < 1"
            assert policy.backoff_seconds, f"{kind} has empty backoff"

    def test_escalation_only_for_circle_directed_kinds(self):
        for kind, policy in POLICIES.items():
            if policy.escalate_on_exhausted:
                assert kind in CIRCLE_DIRECTED_KINDS, (
                    f"{kind} escalates but isn't circle-directed"
                )

    def test_receipt_polling_implies_a_push_channel(self):
        for policy in POLICIES.values():
            if policy.track_expo_receipts:
                assert DeliveryChannel.PUSH in policy.channels

    def test_policy_for_returns_the_entry(self):
        assert (
            policy_for(NotificationKind.CIRCLE_ALERT)
            is POLICIES[NotificationKind.CIRCLE_ALERT]
        )


class TestMakeDedupeKey:
    def test_format_with_user_recipient(self):
        sid = uuid4()
        uid = uuid4()
        key = make_dedupe_key(
            NotificationKind.CIRCLE_ALERT,
            scope_id=sid,
            channel=DeliveryChannel.PUSH,
            recipient_user_id=uid,
        )
        assert key == f"circle_alert:{sid}:u:{uid}:push"

    def test_phone_recipient_uses_p_prefix(self):
        sid = uuid4()
        pid = uuid4()
        key = make_dedupe_key(
            NotificationKind.CIRCLE_ALERT,
            scope_id=sid,
            channel=DeliveryChannel.SMS,
            recipient_phone_id=pid,
        )
        assert key == f"circle_alert:{sid}:p:{pid}:sms"

    def test_is_deterministic(self):
        args = {
            "scope_id": "s1",
            "channel": DeliveryChannel.PUSH,
            "recipient_user_id": "u1",
        }
        assert make_dedupe_key(
            NotificationKind.OWNER_REMINDER, **args
        ) == make_dedupe_key(NotificationKind.OWNER_REMINDER, **args)

    def test_occurrence_disambiguates(self):
        base = {
            "scope_id": "s1",
            "channel": DeliveryChannel.PUSH,
            "recipient_user_id": "u1",
        }
        a = make_dedupe_key(NotificationKind.OWNER_REMINDER, **base, occurrence="30")
        b = make_dedupe_key(NotificationKind.OWNER_REMINDER, **base, occurrence="10")
        assert a != b
        assert a.endswith(":30")
