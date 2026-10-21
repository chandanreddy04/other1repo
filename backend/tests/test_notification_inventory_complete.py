"""docs/notifications.md names every notification constant.

docs/notifications.md is the inventory of every push/SMS template and its
trigger (CLAUDE.md "All push/SMS templates and their triggers"). A constant
added to app/services/notification_constants.py without a doc entry makes
the inventory silently incomplete, so every module-level UPPER_CASE name
there must appear in the doc — either verbatim or through a `FOO_*` prefix
mention (e.g. `CIRCLE_EMPTIED_*` covers `CIRCLE_EMPTIED_TITLE`/`_BODY`).

Related: docs/notifications.md, app/services/notification_constants.py,
tests/test_api_reference_routes_exist.py (the same pin for the API doc).
"""

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_CONSTANTS = _REPO / "backend/app/services/notification_constants.py"
_DOC = _REPO / "docs/notifications.md"

_UPPER = re.compile(r"[A-Z][A-Z0-9_]*")
_PREFIX_MENTION = re.compile(r"\b([A-Z][A-Z0-9_]*_)\*")


def _constant_names() -> list[str]:
    names = []
    for stmt in ast.parse(_CONSTANTS.read_text(encoding="utf-8")).body:
        if isinstance(stmt, ast.Assign):
            targets = stmt.targets
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
        else:
            continue
        names += [
            t.id for t in targets if isinstance(t, ast.Name) and _UPPER.fullmatch(t.id)
        ]
    return names


def test_constants_module_parses_to_a_real_inventory():
    assert len(_constant_names()) > 20, "found suspiciously few constants"


def test_every_notification_constant_is_documented():
    doc = _DOC.read_text(encoding="utf-8")
    prefixes = set(_PREFIX_MENTION.findall(doc))
    missing = [
        name
        for name in _constant_names()
        if not re.search(r"(?<![A-Z0-9_])" + name + r"(?![A-Z0-9_])", doc)
        and not any(name.startswith(prefix) for prefix in prefixes)
    ]
    assert not missing, (
        "notification constants missing from docs/notifications.md (name each "
        "one, or a FOO_* prefix):\n" + "\n".join(missing)
    )
