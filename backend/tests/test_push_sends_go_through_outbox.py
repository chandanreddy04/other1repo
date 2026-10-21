"""Pushes are sent only by the notification-outbox reconciler.

Every push must be auditable: a `NotificationDelivery` row, retries and an
Expo receipt (`track_expo_receipts`). That only happens when the send goes
through `app/services/notification_outbox.py`, so a
`.send_notification(...)` call (ExpoPushNotificationService, the push
provider) anywhere else in backend/app fails this test.

ALLOWED_DIRECT held the pre-existing direct callers, keyed (module,
enclosing function) and dated. It could only shrink, and is now empty: the
last two (the account-holder STOP pushes in notification_helpers.py) moved to
outbox kinds on 2026-09-27. `test_scanner_finds_exactly_the_outbox_dispatcher`
pins both halves — the allowlist stays empty, and the scanner still detects
the one real caller (`_dispatch_push`), so the "only from the outbox" check
can't pass vacuously because the scanner stopped seeing calls.

Related: app/services/notification_outbox.py, app/services/expo_notifications.py,
tests/test_direct_pushes_via_outbox.py (behavioral), .claude/rules/testing.md.
"""

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"

_SEND_ATTR = "send_notification"
_OUTBOX = "services/notification_outbox.py"
_OUTBOX_DISPATCHER = "_dispatch_push"

# (module relative to backend/app, enclosing function) -> date + reason.
ALLOWED_DIRECT: dict[tuple[str, str], str] = {}


def _provider_calls() -> list[tuple[str, str, int]]:
    """(module, enclosing function or '<module>', line) per provider send."""
    calls = []
    for path in sorted(_APP.rglob("*.py")):
        rel = path.relative_to(_APP).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))

        def visit(node: ast.AST, func: str, rel: str = rel) -> None:
            for child in ast.iter_child_nodes(node):
                name = func
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    name = child.name
                if isinstance(child, ast.Call):
                    target = child.func
                    called = (
                        target.attr
                        if isinstance(target, ast.Attribute)
                        else target.id
                        if isinstance(target, ast.Name)
                        else None
                    )
                    if called == _SEND_ATTR:
                        calls.append((rel, func, child.lineno))
                visit(child, name)

        visit(tree, "<module>")
    return calls


def test_outbox_still_sends_pushes():
    assert any(rel == _OUTBOX for rel, _, _ in _provider_calls()), (
        "no provider send found in the outbox — did the provider method move? "
        "Update _SEND_ATTR."
    )


def test_push_provider_is_called_only_from_the_outbox():
    stray = [
        f"{rel}:{line} ({func})"
        for rel, func, line in _provider_calls()
        if rel != _OUTBOX and (rel, func) not in ALLOWED_DIRECT
    ]
    assert not stray, (
        "push sent outside notification_outbox.py — enqueue a delivery row "
        "instead so it is retried and receipt-tracked:\n" + "\n".join(stray)
    )


def test_scanner_finds_exactly_the_outbox_dispatcher():
    """Self-check for the scanner: with an empty allowlist the stray check
    above would pass vacuously if `_provider_calls` stopped matching calls.
    It must find the reconciler's push dispatcher — and nothing else."""
    assert ALLOWED_DIRECT == {}, (
        "ALLOWED_DIRECT is closed — route the push through an outbox kind "
        "instead of allowlisting a direct caller"
    )
    callers = {(rel, func) for rel, func, _ in _provider_calls()}
    assert callers == {(_OUTBOX, _OUTBOX_DISPATCHER)}, callers
