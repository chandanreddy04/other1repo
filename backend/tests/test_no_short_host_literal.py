"""The short-link host comes from settings, never a hard-coded literal.

`settings.SHORT_DOMAIN` (app/core/config.py) is the one place the short host
`madeitho.me` is spelled out, so staging/dev can point short links at their
own host. A literal elsewhere in backend/app silently ships production URLs
from every environment.

Scans non-docstring string constants in backend/app/**/*.py via the AST
(comments and docstrings that merely mention the host are fine). There are
no exceptions: the last one (sub_lapse_notifications.SUB_SHORT_URL) now builds
on SHORT_DOMAIN. A self-check proves the scanner still sees the host where it
IS spelled out (core/config.py), so an empty result can't mean a broken scan.

Related: app/core/config.py (SHORT_DOMAIN), app/web/short_links.py.
"""

import ast
from pathlib import Path

_APP = Path(__file__).resolve().parents[1] / "app"
_HOST = "madeitho.me"
_CONFIG = "core/config.py"


def _docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            )
            and node.body
        ):
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                ids.add(id(first.value))
    return ids


def _file_hits(path: Path) -> list[tuple[str, int, str]]:
    """(module, line, value) per non-docstring host literal in one file."""
    rel = path.relative_to(_APP).as_posix()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = _docstring_nodes(tree)
    return [
        (rel, node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and _HOST in node.value
        and id(node) not in docstrings
    ]


def _hits() -> list[tuple[str, int, str]]:
    out = []
    for path in sorted(_APP.rglob("*.py")):
        if path.relative_to(_APP).as_posix() != _CONFIG:
            out.extend(_file_hits(path))
    return out


def test_no_short_host_literal_outside_config():
    stray = [f"{rel}:{line}: {value!r}" for rel, line, value in _hits()]
    assert not stray, (
        f"{_HOST!r} literal outside core/config.py — use settings.SHORT_DOMAIN:\n"
        + "\n".join(stray)
    )


def test_scanner_sees_the_config_spelling():
    # Non-vacuity: the one sanctioned spelling (SHORT_DOMAIN's default) must be
    # detected, or the empty result above proves nothing.
    assert any(
        value.startswith(f"https://{_HOST}")
        for _, _, value in _file_hits(_APP / _CONFIG)
    ), f"scanner found no {_HOST!r} literal in {_CONFIG} — the scan is broken"
