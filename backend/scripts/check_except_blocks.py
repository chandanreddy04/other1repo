"""Every swallowed exception is reported, or explicitly benign.

Walks the AST of app/, worker_tick.py and worker_loop.py. An ``except`` block
passes if its body re-raises, logs at a Bugsnag-forwarded level
(``logger.error`` / ``.exception`` / ``.critical`` — see
app/core/error_reporting.py) or calls ``notify``; otherwise the ``except``
line, the line above it, or the first body line must carry ``# benign: <why>``.
A ``contextlib.suppress(...)`` needs the same comment on or next to its line.

Why: before 2026-09-06 dozens of ``except ...: logger.warning(...)`` blocks on
the alert/SMS/worker paths looked handled and reported nothing. Gate wired into
``make backend-lint`` and .pre-commit-config.yaml.

    python scripts/check_except_blocks.py            # from backend/

Related: .claude/rules/backend-conventions.md, mobile/eslint.config.mjs (the
mobile twin of this rule).
"""

from __future__ import annotations

import ast
import io
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("app",)
SCAN_FILES = ("worker_tick.py", "worker_loop.py")
REPORTING_ATTRS = {"error", "exception", "critical", "notify"}
REPORTING_NAMES = {
    "notify",
    "report_error",
}  # app.core.error_reporting.notify (aliases)
LOGGER_NAMES = {"logger", "log", "root"}
BENIGN_MARKER = "benign:"


def _comments_by_line(src: str) -> dict[int, str]:
    out: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            out[tok.start[0]] = tok.string
    return out


def _is_report_call(node: ast.AST) -> bool:
    if isinstance(node, ast.Await):
        node = node.value
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if isinstance(func, ast.Attribute) and func.attr in REPORTING_ATTRS:
        return _is_logger(func.value) and not _skips_forwarding(node)
    return isinstance(func, ast.Name) and func.id in REPORTING_NAMES


def _skips_forwarding(call: ast.Call) -> bool:
    """`logger.error(..., extra={"error_report_skip": True})` is deliberately
    NOT forwarded (main.py / error_handler.py pair it with an explicit notify),
    so on its own it reports nothing."""
    for kw in call.keywords:
        if kw.arg == "extra" and isinstance(kw.value, ast.Dict):
            for key in kw.value.keys:
                if isinstance(key, ast.Constant) and key.value == "error_report_skip":
                    return True
    return False


def _is_logger(node: ast.AST) -> bool:
    """`logger.error(...)`, `self.logger.exception(...)`, `logging.getLogger(...)
    .error(...)` — not `result.error(...)` or `dialog.error(...)`."""
    if isinstance(node, ast.Call):
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        return name == "getLogger"
    if isinstance(node, ast.Name):
        name = node.id
    elif isinstance(node, ast.Attribute):
        name = node.attr
    else:
        return False
    return name in LOGGER_NAMES or name.endswith(("logger", "_log"))


_EXITS = (ast.Return, ast.Continue, ast.Break)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)


def _exits_conditionally(stmt: ast.stmt) -> bool:
    """A `return`/`continue`/`break` nested inside `stmt` (an `if`, `for`, ...)
    — a path that leaves the handler before any report below it runs."""
    for node in ast.walk(stmt):
        if isinstance(node, _SCOPES):
            continue
        if isinstance(node, _EXITS):
            return True
    return False


def _reports(handler: ast.ExceptHandler) -> bool:
    """Only an UNCONDITIONAL report counts: a `raise` or a logger/notify call
    that is a direct statement of the handler body, with no conditional exit
    (`if x: return`) ahead of it. A raise inside an `if` or a nested try leaves
    the other path silent — that path needs `# benign:`."""
    for stmt in handler.body:
        if isinstance(stmt, ast.Raise):
            return True
        if isinstance(stmt, ast.Expr) and _is_report_call(stmt.value):
            return True
        if _exits_conditionally(stmt):
            return False
    return False


def _benign(comments: dict[int, str], first: int, last: int) -> bool:
    return any(
        BENIGN_MARKER in comments.get(line, "") for line in range(first, last + 1)
    )


def check_source(src: str, rel: str) -> list[str]:
    tree = ast.parse(src, filename=rel)
    comments = _comments_by_line(src)
    problems: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            first_body = node.body[0].lineno if node.body else node.lineno
            if not _reports(node) and not _benign(
                comments, node.lineno - 1, first_body
            ):
                problems.append(
                    f"{rel}:{node.lineno}: except block neither reports "
                    f"(logger.error/exception/critical, raise, notify) nor says `# benign: <why>`"
                )
        elif isinstance(node, ast.withitem):
            ctx = node.context_expr
            func = getattr(ctx, "func", None)
            name = getattr(func, "attr", None) or getattr(func, "id", None)
            if (
                isinstance(ctx, ast.Call)
                and name == "suppress"
                and not _benign(comments, ctx.lineno - 1, ctx.lineno + 1)
            ):
                problems.append(
                    f"{rel}:{ctx.lineno}: contextlib.suppress without a `# benign: <why>` comment"
                )
    return problems


def main() -> int:
    files = [p for d in SCAN_DIRS for p in sorted((ROOT / d).rglob("*.py"))]
    files += [ROOT / f for f in SCAN_FILES]
    problems: list[str] = []
    for path in files:
        problems += check_source(path.read_text(), str(path.relative_to(ROOT)))
    if problems:
        sys.stderr.write(
            "✗ swallowed exceptions that neither report nor explain themselves:\n  "
            + "\n  ".join(problems)
            + "\n"
        )
        return 1
    sys.stdout.write(
        f"✓ every except/suppress in {len(files)} files reports or is marked benign\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
