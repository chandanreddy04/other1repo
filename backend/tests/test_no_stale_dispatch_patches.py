"""Guard: tests must patch push/SMS dispatch where it actually happens.

Notification dispatch (Expo push + gated SMS) for the session pipeline moved
into the reconciler, `app.services.notification_outbox`. `session_tasks` and
`alert_acknowledgement` only ENQUEUE delivery rows now — they no longer import
`ExpoPushNotificationService` or `sms_opt_out`. A test that patches
`session_tasks.ExpoPushNotificationService` / `session_tasks.sms_opt_out`
(or the `alert_acknowledgement` equivalents) is a SILENT no-op: the patch target is not on
the code path, so the real provider runs (dev-mode SMS "sends", live Expo call),
and the test passes for the wrong reason — or breaks outright once the stale
import is removed. This bit us repeatedly during the outbox migration, so it's
enforced here rather than left to review.

`group_plan_service.grant_grace_period_to_members` and
`sub_lapse_notifications._send_to_user` also ride the outbox (owner decision:
every push auditable) — they do not import the providers directly either.

Patch the reconciler instead:
    @patch("app.services.notification_outbox.ExpoPushNotificationService...")
    @patch("app.services.notification_outbox.sms_opt_out.gated_send_sms", ...)

Related: services/notification_outbox.py (the reconciler / dispatch),
         services/session_tasks.py + services/alert_acknowledgement.py +
         services/group_plan_service.py + services/sub_lapse_notifications.py
         (all enqueue-only).
"""

import re
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Modules that no longer dispatch — patching these bindings does nothing.
_STALE_PATCH_TARGETS = [
    "app.services.session_tasks.ExpoPushNotificationService",
    "app.services.session_tasks.sms_opt_out",
    "app.services.alert_acknowledgement.ExpoPushNotificationService",
    "app.services.alert_acknowledgement.sms_opt_out",
    "app.services.group_plan_service.ExpoPushNotificationService",
    "app.services.group_plan_service.sms_opt_out",
    "app.services.sub_lapse_notifications.ExpoPushNotificationService",
    "app.services.sub_lapse_notifications.sms_opt_out",
]


def test_no_test_patches_a_stale_dispatch_binding():
    offenders: list[str] = []
    for path in TESTS_DIR.glob("test_*.py"):
        if path.name == Path(__file__).name:
            continue
        text = path.read_text()
        for target in _STALE_PATCH_TARGETS:
            # Match the target inside a patch(...) string literal.
            if re.search(rf"patch\(\s*[\"'']{re.escape(target)}", text):
                offenders.append(f"{path.name}: patches {target}")
    assert not offenders, (
        "These tests patch a dispatch binding that no longer exists on the code "
        "path (dispatch moved to notification_outbox — the patch is a silent "
        "no-op). Repoint them to app.services.notification_outbox.*:\n  "
        + "\n  ".join(offenders)
    )
