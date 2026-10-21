"""No phone number may be passed to a log call that reaches Bugsnag.

``logger.error`` / ``logger.exception`` / ``logger.critical`` now forward to
Bugsnag through the root-logger handler (app/core/error_reporting.py), and only
``user.id`` may go there (security.md). The two existing guards cover
``extra={...}`` dict keys and f-strings in a few SMS/auth files; this one walks
the AST of EVERY backend module and flags phone-named *positional* arguments —
the ``logger.warning("... %s", referrer.phone_number)`` shape that slipped past
both (services/referral.py, fixed 2026-09-06). ``warning`` is included so a
later promotion to ERROR can't start leaking.

Allowed: wrapping the value in ``phone_tag(...)`` / ``_phone_tag(...)`` (a hash).

Related: tests/test_no_phone_in_log_extras.py, tests/test_log_phone_pii_guard.py,
app/utils/phone.py.
"""

import ast
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
LEVELS = {"error", "exception", "critical", "warning"}
HASH_WRAPPERS = {"phone_tag", "_phone_tag"}


def _names_a_phone(node: ast.AST) -> bool:
    if isinstance(node, ast.Name):
        return "phone" in node.id.lower()
    if isinstance(node, ast.Attribute):
        return "phone" in node.attr.lower()
    return False


def _is_hashed(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in HASH_WRAPPERS
    )


def _phone_leaks(call: ast.Call) -> list[str]:
    leaks: list[str] = []
    for arg in call.args[1:]:
        if _is_hashed(arg):
            continue
        if _names_a_phone(arg):
            leaks.append(ast.unparse(arg))
    for arg in call.args[:1]:
        # f-string message: every formatted value is checked too.
        if isinstance(arg, ast.JoinedStr):
            for value in arg.values:
                if (
                    isinstance(value, ast.FormattedValue)
                    and not _is_hashed(value.value)
                    and _names_a_phone(value.value)
                ):
                    leaks.append(ast.unparse(value.value))
    return leaks


def test_no_phone_positional_args_in_bugsnag_level_logs():
    offenders: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if node.func.attr not in LEVELS:
                continue
            if not (
                isinstance(node.func.value, ast.Name)
                and "log" in node.func.value.id.lower()
            ):
                continue
            for leak in _phone_leaks(node):
                offenders.append(
                    f"{path.relative_to(APP_DIR.parent)}:{node.lineno} — {leak}"
                )
    assert not offenders, (
        "phone-named values passed to a Bugsnag-forwarded log call "
        "(log user.id, or wrap in phone_tag()):\n" + "\n".join(offenders)
    )
