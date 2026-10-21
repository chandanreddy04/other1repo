"""Guard against phone PII reaching the structured logger.

`security.md` is strict: phones are PII; only `user.id` goes to Bugsnag,
which is the destination for `logger.exception` / `logger.error`. The
audit caught `extra={"from": from_phone}` in the inbound SMS webhook —
that pattern would have shipped phone numbers straight into the error
tracker.

This test walks the AST of every backend source file, finds any
`logger.<level>(... extra=...)` call where the level is one that goes
to Bugsnag, and flags dict literals whose keys name a phone-like field.
The intent isn't to be a fancy taint tracker — it's to catch the
exact "I forgot to hash this" antipattern at CI time.

Use `extra={"phone_tag": _phone_tag(phone)}` (or omit the field
entirely) instead. See `app/api/v1/endpoints/inbound_sms.py:_phone_tag`
for the hash helper.
"""

import ast
from pathlib import Path

import pytest

APP_DIR = Path(__file__).parent.parent / "app"

# Log levels that forward to Bugsnag (per `app/core/logging.py` setup).
# `info` is intentionally NOT here — info logs go to structured
# logging but not error tracking.
_BUGSNAG_LEVELS = frozenset({"exception", "error", "critical"})

# Dict keys that name a phone-like field. Conservative — adding a new
# entry here is cheap and catches a class of leaks at once.
_PHONE_KEY_NAMES = frozenset(
    {
        "from",
        "to",
        "phone",
        "phone_number",
        "from_phone",
        "to_phone",
        "recipient",
        "sender",
    }
)


def _find_violations(tree: ast.AST, path: Path) -> list[tuple[Path, int, str]]:
    out: list[tuple[Path, int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Match `logger.<level>(...)` shape.
        if not (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
            and node.func.attr in _BUGSNAG_LEVELS
        ):
            continue
        # Look for an `extra=` kwarg that's a dict literal.
        for kw in node.keywords:
            if kw.arg != "extra" or not isinstance(kw.value, ast.Dict):
                continue
            for key in kw.value.keys:
                if (
                    isinstance(key, ast.Constant)
                    and isinstance(key.value, str)
                    and key.value in _PHONE_KEY_NAMES
                ):
                    out.append((path, node.lineno, key.value))
    return out


@pytest.fixture(scope="module")
def violations() -> list[tuple[Path, int, str]]:
    findings: list[tuple[Path, int, str]] = []
    for path in APP_DIR.rglob("*.py"):
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        findings.extend(_find_violations(tree, path))
    return findings


def test_no_phone_keyed_extras_in_bugsnag_loggers(
    violations: list[tuple[Path, int, str]],
) -> None:
    if not violations:
        return
    msg_lines = [
        f"  {p.relative_to(APP_DIR.parent)}:{lineno}: extra={{{key!r}: ...}}"
        for p, lineno, key in violations
    ]
    pytest.fail(
        "Phone-like keys found in logger.exception/error/critical extras "
        "(forwarded to Bugsnag — security.md forbids phone PII there). "
        "Use a hashed `phone_tag` or omit the field:\n"
        + "\n".join(msg_lines)
    )
