"""Code names are functional, never bound to the vendor underneath.

``app/core/error_reporting.py`` wraps Bugsnag; the module, the admin route
(``/admin/error-reporting-test``), the startup check and the make target are
named after what they do, so swapping the vendor is a one-module change and
docs/routes never lie. This pins it: no function, class, module-level name or
route in ``app/`` may carry the vendor's name. The SDK's own symbols
(``bugsnag``, ``BugsnagHandler``) and the credential setting
(``BUGSNAG_API_KEY`` — it IS the vendor's key) are the allowed exceptions.

Why: 2026-09-06 shipped ``bugsnag.py``, ``/admin/bugsnag-test``,
``_check_bugsnag`` and ``init_bugsnag`` before review caught each one.

Related: mobile/eslint.config.mjs (the mobile twin, `no-restricted-syntax`),
~/.claude/CLAUDE.md naming rule.
"""

import ast
from pathlib import Path

from app.main import app

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    *sorted((ROOT / "app").rglob("*.py")),
    ROOT / "worker_tick.py",
    ROOT / "worker_loop.py",
]
VENDOR = "bugsnag"
ALLOWED = {"bugsnag", "BugsnagHandler", "BUGSNAG_API_KEY"}


def _named_things(tree: ast.AST) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.append((node.lineno, node.name))
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            out.extend((t.lineno, t.id) for t in targets if isinstance(t, ast.Name))
    return out


def test_no_vendor_named_definitions() -> None:
    offenders = [
        f"{path.relative_to(ROOT)}:{line}: {name}"
        for path in FILES
        for line, name in _named_things(ast.parse(path.read_text()))
        if VENDOR in name.lower() and name not in ALLOWED
    ]
    assert offenders == [], "name these after what they do:\n  " + "\n  ".join(
        offenders
    )


def test_no_vendor_named_modules_or_routes() -> None:
    modules = [str(p.relative_to(ROOT)) for p in FILES if VENDOR in p.stem.lower()]
    assert modules == [], modules
    routes = [
        path
        for path in {getattr(r, "path", "") for r in app.routes}
        if VENDOR in path.lower()
    ]
    assert routes == [], routes
